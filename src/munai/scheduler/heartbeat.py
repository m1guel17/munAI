"""Heartbeat scheduler: proactive agent runs triggered on a schedule."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..agent.runtime import AgentRuntime
    from ..audit.logger import AuditLogger
    from ..channels.pairing import PairingManager
    from ..channels.telegram import TelegramAdapter
    from ..config import Config
    from ..gateway.session_manager import SessionManager
    from ..gateway.session_router import SessionRouter

log = logging.getLogger(__name__)

# Stable session key for all heartbeat runs — accumulates context across runs
_HEARTBEAT_SESSION_KEY = "heartbeat:proactive"


class HeartbeatScheduler:
    """Runs the agent on a schedule to perform proactive tasks.

    Workflow per tick:
    1. Read ``HEARTBEAT.md`` from the workspace.
    2. If empty, skip silently.
    3. Run the agent with the heartbeat content as the user prompt.
    4. If the response contains the ack keyword (default ``HEARTBEAT_OK``),
       suppress sending it — the agent acknowledged but has nothing to report.
    5. Otherwise, forward the response to all allowed Telegram users.
    """

    def __init__(
        self,
        config: Config,
        runtime: AgentRuntime,
        telegram: TelegramAdapter | None,
        pairing: PairingManager,
        session_manager: Any,
        session_router: Any,
        audit: AuditLogger,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._telegram = telegram
        self._pairing = pairing
        self._session_manager = session_manager
        self._session_router = session_router
        self._audit = audit
        self._scheduler: Any = None
        self._last_run_at: datetime | None = None
        self._is_running: bool = False
        self._run_history: list[dict[str, Any]] = []  # last 10 entries

    async def start(self) -> None:
        """Start the APScheduler AsyncIOScheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._run_heartbeat,
            "interval",
            id="heartbeat",
            minutes=self._config.heartbeat.interval_minutes,
        )
        self._scheduler.start()
        log.info(
            "Heartbeat scheduler started (interval=%d min)",
            self._config.heartbeat.interval_minutes,
        )

    async def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("Heartbeat scheduler stopped")

    async def run_now(self) -> None:
        """Trigger a heartbeat run immediately, outside of the schedule."""
        await self._run_heartbeat()

    def get_status(self) -> dict[str, Any]:
        """Return current heartbeat job status."""
        next_run_at: str | None = None
        if self._scheduler and self._scheduler.running:
            job = self._scheduler.get_job("heartbeat")
            if job and job.next_run_time:
                next_run_at = job.next_run_time.isoformat()
        return {
            "id": "heartbeat",
            "name": "Heartbeat",
            "enabled": self._config.heartbeat.enabled,
            "interval_minutes": self._config.heartbeat.interval_minutes,
            "ack_keyword": self._config.heartbeat.ack_keyword,
            "is_running": self._is_running,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "next_run_at": next_run_at,
            "run_history": list(self._run_history),
        }

    def update(
        self,
        interval_minutes: int | None = None,
        enabled: bool | None = None,
        ack_keyword: str | None = None,
    ) -> None:
        """Update heartbeat settings and reschedule if interval changed."""
        if interval_minutes is not None and interval_minutes > 0:
            self._config.heartbeat.interval_minutes = interval_minutes
            if self._scheduler and self._scheduler.running:
                job = self._scheduler.get_job("heartbeat")
                if job:
                    job.reschedule(trigger="interval", minutes=interval_minutes)
        if enabled is not None:
            self._config.heartbeat.enabled = enabled
        if ack_keyword is not None:
            self._config.heartbeat.ack_keyword = ack_keyword

    # ─── Internal ─────────────────────────────────────────────────────────────

    async def _run_heartbeat(self) -> None:
        """Execute one heartbeat tick, tracking run history."""
        started_at = datetime.now(timezone.utc)
        self._last_run_at = started_at
        self._is_running = True
        start_mono = asyncio.get_event_loop().time()
        error_msg: str | None = None
        try:
            await self._run_heartbeat_inner()
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            self._is_running = False
            duration_ms = round((asyncio.get_event_loop().time() - start_mono) * 1000)
            entry: dict[str, Any] = {
                "started_at": started_at.isoformat(),
                "duration_ms": duration_ms,
                "ok": error_msg is None,
                "error": error_msg,
            }
            self._run_history.append(entry)
            if len(self._run_history) > 10:
                self._run_history = self._run_history[-10:]

    async def _run_heartbeat_inner(self) -> None:
        """Inner heartbeat logic (split to allow _is_running tracking)."""
        heartbeat_content = self._read_heartbeat_md()
        if not heartbeat_content:
            log.debug("HEARTBEAT.md is empty — skipping heartbeat run")
            return

        prompt = f"[HEARTBEAT RUN]\n\n{heartbeat_content}"

        # Resolve a stable session for heartbeat continuity
        session_id = self._session_router.get_or_create_session(_HEARTBEAT_SESSION_KEY)

        # Build a capture emit: stores agent.done text, ignores deltas
        response_holder: dict[str, str] = {}

        async def capture_emit(event_name: str, payload: dict[str, Any]) -> None:
            if event_name == "agent.done":
                response_holder["text"] = payload.get("text", "")

        # Use heartbeat-specific model if configured
        runtime = self._get_heartbeat_runtime()

        try:
            await runtime.run_turn(
                session_id=session_id,
                channel="heartbeat",
                sender_id="scheduler",
                text=prompt,
                emit=capture_emit,
            )
        except Exception as exc:
            log.error("Heartbeat agent run failed: %s", exc)
            await self._audit.log(
                "heartbeat.error",
                detail={"error": str(exc)},
                session_id=session_id,
                channel="heartbeat",
            )
            return

        response_text = response_holder.get("text", "")
        ack_keyword = self._config.heartbeat.ack_keyword
        suppressed = bool(ack_keyword and ack_keyword in response_text)

        await self._audit.log(
            "heartbeat.run",
            detail={
                "suppressed": suppressed,
                "text_length": len(response_text),
            },
            session_id=session_id,
            channel="heartbeat",
        )

        if suppressed:
            log.debug("Heartbeat suppressed (response contained ack keyword)")
            return

        # Forward response to all Telegram users
        if self._telegram and response_text:
            recipients = list(set(
                self._pairing.get_allowed_users()
                + self._config.channels.telegram.allow_from
            ))
            for user_id in recipients:
                try:
                    await self._telegram.send_message(int(user_id), response_text)
                except (ValueError, Exception) as exc:
                    log.warning("Failed to send heartbeat to %s: %s", user_id, exc)

    def _read_heartbeat_md(self) -> str:
        """Read HEARTBEAT.md and return stripped content (empty string if blank)."""
        heartbeat_path = self._config.agent.workspace_path / "HEARTBEAT.md"
        if not heartbeat_path.exists():
            return ""
        try:
            content = heartbeat_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            log.warning("Could not read HEARTBEAT.md: %s", exc)
            return ""
        # Treat files that are only comments as empty
        meaningful_lines = [
            line for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return content if meaningful_lines else ""

    def _get_heartbeat_runtime(self) -> AgentRuntime:
        """Return an AgentRuntime configured with the heartbeat model, if set."""
        heartbeat_name = self._config.models.heartbeat
        if heartbeat_name is None:
            return self._runtime

        # Build a modified config that uses the heartbeat provider as primary.
        # The providers dict is shared (ProviderConfig is immutable Pydantic model).
        from copy import deepcopy
        from ..agent.runtime import AgentRuntime
        from ..config import ModelsConfig

        modified_models = ModelsConfig(
            primary=heartbeat_name,
            fallback=[],
            providers=self._config.models.providers,
        )
        modified_config = deepcopy(self._config)
        object.__setattr__(modified_config, "models", modified_models)

        return AgentRuntime(
            config=modified_config,
            session_manager=self._session_manager,
            audit=self._audit,
        )
