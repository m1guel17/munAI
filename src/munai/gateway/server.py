"""aiohttp Gateway server: WebSocket control plane + HTTP file server."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from ..agent.runtime import AgentRuntime
from ..agent.session import SessionManager
from ..audit.logger import AuditLogger
from ..audit.redactor import Redactor
from ..channels.pairing import PairingManager
from ..channels.webchat import WebchatAdapter
from ..config import Config, MUNAI_DIR
from ..workspace.bootstrap import ensure_workspace
from .approval import ApprovalManager
from .auth import GatewayAuth
from .lane_queue import LaneQueue
from .protocol import (
    EventMessage,
    RequestMessage,
    ResponseMessage,
    parse_inbound,
)
from .session_router import SessionRouter

log = logging.getLogger(__name__)

# ui/ directory: src/munai/gateway/server.py → munAI/ui/
UI_DIR = Path(__file__).parent.parent.parent.parent / "ui"


class GatewayServer:
    """Main Gateway process.

    Wires together all components. Per-connection state lives in local
    variables inside _handle_websocket, not on self.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

        redactor = Redactor(config.tools.redact_patterns)
        self._audit = AuditLogger(
            redactor=redactor if config.audit.redact_in_audit else None,
            enabled=config.audit.enabled,
        )
        self._auth = GatewayAuth(config.gateway.resolve_token())
        self._approval_mgr = ApprovalManager()
        self._lane_queue = LaneQueue()

        self._session_manager = SessionManager()
        self._session_router = SessionRouter(self._session_manager)
        self._webchat = WebchatAdapter()
        self._agent = AgentRuntime(
            config=config,
            session_manager=self._session_manager,
            audit=self._audit,
            request_approval=self._handle_approval_request,
        )

        # Pairing manager (shared between Telegram adapter and heartbeat)
        self._pairing = PairingManager(MUNAI_DIR / "pairing.json")

        # Optional Phase 3 services (started in start(), stopped in stop())
        self._telegram: Any = None
        self._heartbeat: Any = None

        # client_id → WebSocketResponse
        self._ws_connections: dict[str, web.WebSocketResponse] = {}
        # client_id → monotonically increasing event sequence number
        self._ws_seq: dict[str, int] = {}
        # session_id → client_id (for routing approval events)
        self._session_to_client: dict[str, str] = {}

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        # session_key → asyncio.Event; set to abort a running agent turn
        self._abort_events: dict[str, asyncio.Event] = {}
        # monotonic start time for uptime calculation
        self._start_time: float = time.monotonic()
        # kill switch: when True, new agent requests are blocked
        self._emergency_stopped: bool = False
        # session_key → per-session override dict (model, verbose, thinking_mode)
        self._session_overrides: dict[str, dict] = {}
        # custom cron jobs (keyed by job id), loaded from cron.json
        self._custom_jobs: dict[str, dict] = self._load_custom_jobs()

    async def start(self) -> None:
        """Initialize workspace, build routes, start listening."""
        ensure_workspace(self._config.agent.workspace_path)

        # Audit retention cleanup on startup
        cleaned = await self._audit.cleanup_old_logs(self._config.audit.retention_days)
        if cleaned:
            log.info("Cleaned %d old audit file(s)", cleaned)

        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_get("/api/health", self._handle_health)
        self._app.router.add_get("/api/audit", self._handle_audit_api)
        self._app.router.add_get("/api/sessions", self._handle_sessions_list)
        self._app.router.add_get("/api/sessions/{session_id}", self._handle_session_detail)
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/static/{path_info:.*}", self._handle_static)
        self._app.on_shutdown.append(self._on_shutdown)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._config.gateway.bind,
            self._config.gateway.port,
        )
        await self._site.start()
        log.info(
            "Munai gateway listening on http://%s:%d",
            self._config.gateway.bind,
            self._config.gateway.port,
        )

        # ── Start Telegram adapter (optional) ─────────────────────────────────
        if self._config.channels.telegram.enabled:
            try:
                from ..channels.telegram import TelegramAdapter
                self._telegram = TelegramAdapter(
                    config=self._config.channels.telegram,
                    pairing=self._pairing,
                    lane_queue=self._lane_queue,
                    session_router=self._session_router,
                    runtime=self._agent,
                    audit=self._audit,
                )
                await self._telegram.connect()
                code = self._pairing.generate_code()
                print(f"  Telegram pairing code: {code}  (valid 24h)")
            except ImportError as exc:
                log.warning("Telegram disabled: %s", exc)
                self._telegram = None

        # ── Start heartbeat scheduler (optional) ──────────────────────────────
        if self._config.heartbeat.enabled:
            from ..scheduler.heartbeat import HeartbeatScheduler
            self._heartbeat = HeartbeatScheduler(
                config=self._config,
                runtime=self._agent,
                telegram=self._telegram,
                pairing=self._pairing,
                session_manager=self._session_manager,
                session_router=self._session_router,
                audit=self._audit,
            )
            await self._heartbeat.start()

    async def stop(self) -> None:
        if self._heartbeat:
            await self._heartbeat.stop()
        if self._telegram:
            await self._telegram.disconnect()
        if self._runner:
            await self._runner.cleanup()
        await self._lane_queue.shutdown()
        await self._audit.close()

    async def _on_shutdown(self, app: web.Application) -> None:
        if self._heartbeat:
            await self._heartbeat.stop()
        if self._telegram:
            await self._telegram.disconnect()
        await self._lane_queue.shutdown()
        await self._audit.close()

    # ─── Approval bridge ─────────────────────────────────────────────────────

    async def _handle_approval_request(
        self,
        approval_id: str,
        command: list[str],
        session_id: str,
    ) -> bool:
        """Called by AgentRuntime when shell_exec needs user approval."""
        client_id = self._session_to_client.get(session_id, "")

        async def emit_approval(event_name: str, payload: dict[str, Any]) -> None:
            await self._emit(client_id, event_name, payload)

        return await self._approval_mgr.request_approval(
            approval_id=approval_id,
            command=command,
            session_id=session_id,
            emit_fn=emit_approval,
        )

    # ─── HTTP Handlers ────────────────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = UI_DIR / "index.html"
        if not index_path.exists():
            return web.Response(
                text="Web UI not found. Run from the project root directory.",
                status=404,
            )
        return web.FileResponse(index_path)

    async def _handle_static(self, request: web.Request) -> web.Response:
        path_info = request.match_info["path_info"]
        try:
            target = (UI_DIR / path_info).resolve()
            target.relative_to(UI_DIR.resolve())
        except ValueError:
            raise web.HTTPForbidden()
        if not target.exists() or not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "sessions": len(self._ws_connections),
            "version": "0.1.0",
        })

    async def _handle_audit_api(self, request: web.Request) -> web.Response:
        """Return audit events from a JSONL log file.

        Query params:
          date: YYYY-MM-DD (default: today UTC)
          type: filter by event_type (optional)
          limit: max number of events to return (default: 500)
        """
        from datetime import datetime, timezone

        date_str = request.rel_url.query.get("date")
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        event_type_filter = request.rel_url.query.get("type")
        try:
            limit = int(request.rel_url.query.get("limit", "500"))
        except ValueError:
            limit = 500

        try:
            events, date_str = await self._query_audit(date_str, event_type_filter, limit)
        except OSError as exc:
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({"date": date_str, "events": events, "total": len(events)})

    async def _query_audit(
        self,
        date_str: str,
        event_type_filter: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str]:
        """Read audit events from JSONL, applying date/type/limit filters.

        Returns (events_newest_first, date_str).
        Raises OSError on read failure.
        """
        from datetime import datetime, timezone
        from ..audit.logger import AUDIT_DIR

        if not date_str or date_str == "today":
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        log_path = AUDIT_DIR / f"{date_str}.jsonl"
        events: list[dict[str, Any]] = []

        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event_type_filter and event.get("event_type") != event_type_filter:
                        continue
                    events.append(event)

        # Newest-first, capped at limit
        return events[-limit:][::-1], date_str

    async def _handle_sessions_list(self, request: web.Request) -> web.Response:
        """GET /api/sessions — list recent sessions newest-first."""
        from ..agent.session import SESSIONS_DIR

        sessions_dir = SESSIONS_DIR
        result: list[dict[str, Any]] = []

        if sessions_dir.exists():
            files = sorted(
                sessions_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for path in files[:50]:
                events = self._read_session_jsonl(path)
                msg_count = sum(1 for e in events if e.get("type") in ("user", "assistant"))
                last_ts = ""
                preview = ""
                for ev in reversed(events):
                    if not last_ts and ev.get("timestamp"):
                        last_ts = ev["timestamp"]
                    if not preview and ev.get("type") == "user":
                        preview = (ev.get("text") or "")[:80]
                    if last_ts and preview:
                        break
                result.append({
                    "session_id": path.stem,
                    "message_count": msg_count,
                    "last_active": last_ts,
                    "preview": preview,
                })

        return web.json_response({"sessions": result})

    async def _handle_session_detail(self, request: web.Request) -> web.Response:
        """GET /api/sessions/{session_id} — return events for a session."""
        from ..agent.session import SESSIONS_DIR

        session_id = request.match_info["session_id"]
        path = SESSIONS_DIR / f"{session_id}.jsonl"
        if not path.exists():
            raise web.HTTPNotFound(reason=f"Session not found: {session_id}")

        events = self._read_session_jsonl(path)
        return web.json_response({"session_id": session_id, "events": events})

    @staticmethod
    def _read_session_jsonl(path) -> list[dict[str, Any]]:
        events = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
        return events

    # ─── WebSocket Handler ────────────────────────────────────────────────────

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        client_id: str | None = None

        try:
            # Step 1: First frame must be a connect message
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        frame = parse_inbound(msg.data)
                    except (ValueError, Exception) as exc:
                        log.warning("Malformed handshake frame: %s", exc)
                        await ws.close(code=4000, message=b"Invalid handshake")
                        return ws

                    from .protocol import ConnectMessage
                    if not isinstance(frame, ConnectMessage):
                        await ws.close(code=4000, message=b"Expected connect frame")
                        return ws

                    valid, reason = self._auth.validate_connect(frame)
                    if not valid:
                        await self._audit.log(
                            "gateway.auth_fail",
                            detail={"client_id": frame.client_id, "reason": reason},
                        )
                        await ws.close(code=4001, message=b"Unauthorized")
                        return ws

                    client_id = frame.client_id
                    self._ws_connections[client_id] = ws
                    self._ws_seq[client_id] = 0

                    await self._audit.log(
                        "gateway.connect",
                        detail={"client_id": client_id, "client_type": frame.client_type},
                    )
                    log.info("Client connected: %s (%s)", client_id, frame.client_type)
                    from .protocol import EventMessage
                    await ws.send_str(EventMessage(
                        event="gateway.connected",
                        payload={"client_id": client_id},
                    ).to_json())
                    break
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    return ws

            if client_id is None:
                return ws

            # Step 2: Handle subsequent request frames
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._dispatch(client_id, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    log.warning("WebSocket error for %s: %s", client_id, ws.exception())
                    break
                elif msg.type == web.WSMsgType.CLOSE:
                    break

        finally:
            if client_id:
                self._ws_connections.pop(client_id, None)
                self._ws_seq.pop(client_id, None)
                dead_sessions = [
                    sid for sid, cid in self._session_to_client.items()
                    if cid == client_id
                ]
                for sid in dead_sessions:
                    self._session_to_client.pop(sid, None)
                log.info("Client disconnected: %s", client_id)

        return ws

    async def _dispatch(self, client_id: str, raw: str) -> None:
        try:
            frame = parse_inbound(raw)
        except (ValueError, Exception) as exc:
            log.warning("Malformed frame from %s: %s", client_id, exc)
            await self._send_response(client_id, "unknown", ok=False, error=str(exc))
            return

        from .protocol import ConnectMessage
        if isinstance(frame, ConnectMessage):
            return  # Duplicate connect — ignore

        req: RequestMessage = frame  # type: ignore[assignment]

        if req.method == "agent":
            await self._handle_agent(client_id, req)
        elif req.method == "agent.abort":
            await self._handle_agent_abort(client_id, req)
        elif req.method == "health":
            await self._handle_health_ws(client_id, req)
        elif req.method == "status":
            await self._send_response(
                client_id, req.id, ok=True,
                payload={"sessions": self._session_router.all_sessions()},
            )
        elif req.method == "sessions.reset":
            await self._handle_sessions_reset(client_id, req)
        elif req.method == "sessions.compact":
            await self._handle_sessions_compact(client_id, req)
        elif req.method == "sessions.patch":
            await self._handle_sessions_patch(client_id, req)
        elif req.method == "audit.query":
            await self._handle_audit_query(client_id, req)
        elif req.method == "tool.approve":
            await self._handle_tool_approve(client_id, req)
        elif req.method == "tool.deny":
            await self._handle_tool_deny(client_id, req)
        elif req.method == "tools.list":
            await self._handle_tools_list(client_id, req)
        elif req.method == "tools.set_policy":
            await self._handle_tools_set_policy(client_id, req)
        elif req.method == "approvals.list":
            await self._handle_approvals_list(client_id, req)
        elif req.method == "skills.list":
            await self._handle_skills_list(client_id, req)
        elif req.method == "skills.install":
            await self._handle_skills_install(client_id, req)
        elif req.method == "skills.set_env":
            await self._handle_skills_set_env(client_id, req)
        elif req.method == "channels.status":
            await self._handle_channels_status(client_id, req)
        elif req.method == "cron.list":
            await self._handle_cron_list(client_id, req)
        elif req.method == "cron.run_now":
            await self._handle_cron_run_now(client_id, req)
        elif req.method == "cron.update":
            await self._handle_cron_update(client_id, req)
        elif req.method == "cron.create":
            await self._handle_cron_create(client_id, req)
        elif req.method == "cron.delete":
            await self._handle_cron_delete(client_id, req)
        elif req.method == "gateway.emergency_stop":
            await self._handle_emergency_stop(client_id, req)
        elif req.method == "config.get":
            await self._handle_config_get(client_id, req)
        elif req.method == "config.hash":
            await self._handle_config_hash(client_id, req)
        elif req.method == "config.set":
            await self._handle_config_set(client_id, req)
        elif req.method == "doctor.run":
            await self._handle_doctor_run(client_id, req)
        elif req.method == "secrets.get":
            await self._handle_secrets_get(client_id, req)
        elif req.method == "auth.devices.list":
            await self._handle_auth_devices_list(client_id, req)
        elif req.method == "auth.devices.revoke":
            await self._handle_auth_devices_revoke(client_id, req)
        elif req.method == "gateway.restart":
            await self._handle_gateway_restart(client_id, req)
        elif req.method == "send":
            await self._handle_send(client_id, req)
        else:
            await self._send_response(
                client_id, req.id, ok=False,
                error=f"Unknown method: {req.method}",
            )

    async def _handle_agent(self, client_id: str, req: RequestMessage) -> None:
        if self._emergency_stopped:
            await self._send_response(
                client_id, req.id, ok=False, error="Gateway emergency stop is active"
            )
            return

        text = req.params.get("text", "").strip()
        if not text:
            await self._send_response(
                client_id, req.id, ok=False, error="'text' param is required"
            )
            return

        # Skill injection: if the message starts with a trigger, prepend skill content
        if text.startswith("/"):
            skill = self._agent.context.get_skill_for_message(text)
            if skill:
                text = f"## Active Skill: {skill.name}\n{skill.content}\n\n{text}"

        msg = self._webchat.message_from_request(
            client_id=client_id,
            text=text,
            request_id=req.id,
        )
        session_id = self._session_router.get_or_create_session(msg.session_key)
        self._session_to_client[session_id] = client_id

        await self._send_response(client_id, req.id, ok=True, payload={"queued": True})

        session_key = msg.session_key
        abort_event = asyncio.Event()
        self._abort_events[session_key] = abort_event

        async def work() -> None:
            async def emit(event_name: str, payload: dict[str, Any]) -> None:
                await self._emit(client_id, event_name, payload)

            await self._audit.log(
                "channel.message_in",
                detail={"text_length": len(text)},
                session_id=session_id,
                channel="webchat",
            )

            try:
                await self._agent.run_turn(
                    session_id=session_id,
                    channel="webchat",
                    sender_id=client_id,
                    text=text,
                    emit=emit,
                    abort_event=abort_event,
                )
            finally:
                self._abort_events.pop(session_key, None)

        await self._lane_queue.submit(session_key, work)

    async def _handle_health_ws(self, client_id: str, req: RequestMessage) -> None:
        """Enhanced health response with uptime and all provider info."""
        uptime = int(time.monotonic() - self._start_time)
        primary_name = self._config.models.primary
        primary_provider = self._config.models.providers.get(primary_name)

        providers = [
            {
                "name": name,
                "model": p.model,
                "is_primary": name == primary_name,
                "is_fallback": name in (self._config.models.fallback or []),
                "is_heartbeat": name == self._config.models.heartbeat,
            }
            for name, p in self._config.models.providers.items()
        ]

        await self._send_response(
            client_id, req.id, ok=True,
            payload={
                "status": "ok",
                "sessions": len(self._ws_connections),
                "uptime_seconds": uptime,
                "version": "0.1.0",
                "port": self._config.gateway.port,
                "bind": self._config.gateway.bind,
                "provider": {
                    "name": primary_name,
                    "model": primary_provider.model if primary_provider else "unknown",
                },
                "providers": providers,
            },
        )

    async def _handle_agent_abort(self, client_id: str, req: RequestMessage) -> None:
        """Signal the currently running agent turn to stop."""
        session_key = req.params.get("session_key", "")
        # Look up by any matching session key prefix or exact match
        event = self._abort_events.get(session_key)
        if not event:
            # Try matching by partial key (client may not know full session key)
            for key, ev in self._abort_events.items():
                if key.startswith(session_key) or session_key in key:
                    event = ev
                    break
        if event:
            event.set()
            await self._send_response(client_id, req.id, ok=True, payload={"aborted": True})
        else:
            await self._send_response(
                client_id, req.id, ok=False, error="No active session to abort"
            )

    async def _handle_sessions_reset(self, client_id: str, req: RequestMessage) -> None:
        """Delete a session's JSONL, clearing its history."""
        from ..agent.session import SESSIONS_DIR

        session_id = req.params.get("session_id", "")
        if not session_id:
            await self._send_response(
                client_id, req.id, ok=False, error="session_id required"
            )
            return

        path = SESSIONS_DIR / f"{session_id}.jsonl"
        if path.exists():
            path.unlink()
        await self._audit.log(
            "session.reset",
            detail={"session_id": session_id},
            session_id=session_id,
        )
        await self._send_response(client_id, req.id, ok=True, payload={"reset": True})

    async def _handle_sessions_compact(self, client_id: str, req: RequestMessage) -> None:
        """Trigger context compaction for a session."""
        from ..agent.compaction import apply_compaction

        session_id = req.params.get("session_id", "")
        if not session_id:
            await self._send_response(
                client_id, req.id, ok=False, error="session_id required"
            )
            return

        history = await self._session_manager.load(session_id)
        if not history:
            await self._send_response(
                client_id, req.id, ok=False, error="Session not found or empty"
            )
            return

        summary, turns_compacted = await self._agent._compactor.compact(history)
        if turns_compacted == 0:
            await self._send_response(
                client_id, req.id, ok=True,
                payload={"compacted": 0, "message": "Nothing to compact"}
            )
            return

        new_history, compaction_event = apply_compaction(
            history, summary, turns_compacted, session_id
        )
        await self._session_manager.append(session_id, compaction_event)
        await self._audit.log(
            "session.compact",
            detail={"turns_compacted": turns_compacted},
            session_id=session_id,
        )
        await self._send_response(
            client_id, req.id, ok=True,
            payload={"compacted": turns_compacted, "summary": summary[:200]},
        )

    async def _handle_audit_query(self, client_id: str, req: RequestMessage) -> None:
        """Return filtered audit events over WebSocket."""
        date_str = req.params.get("date", "today")
        event_type_filter = req.params.get("type", "") or None
        try:
            limit = min(int(req.params.get("limit", 200)), 1000)
        except (ValueError, TypeError):
            limit = 200

        try:
            events, date_str = await self._query_audit(date_str, event_type_filter, limit)
        except OSError as exc:
            await self._send_response(
                client_id, req.id, ok=False, error=str(exc)
            )
            return

        await self._send_response(
            client_id, req.id, ok=True,
            payload={"date": date_str, "events": events, "total": len(events)},
        )

    async def _handle_tool_approve(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Client approved a pending shell command."""
        approval_id = req.params.get("approval_id", "")
        found = self._approval_mgr.approve(approval_id)
        await self._send_response(
            client_id, req.id, ok=found,
            error=None if found else f"Unknown or expired approval_id: {approval_id!r}",
        )

    async def _handle_tool_deny(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Client denied a pending shell command."""
        approval_id = req.params.get("approval_id", "")
        found = self._approval_mgr.deny(approval_id)
        await self._send_response(
            client_id, req.id, ok=found,
            error=None if found else f"Unknown or expired approval_id: {approval_id!r}",
        )

    # ─── Phase 2 handlers ────────────────────────────────────────────────────

    async def _handle_tools_list(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return all tools with enabled status and current policy."""
        from ..tools.file_read import SCHEMA as FR_SCHEMA
        from ..tools.file_write import SCHEMA as FW_SCHEMA
        from ..tools.file_edit import SCHEMA as FE_SCHEMA
        from ..tools.shell_exec import SCHEMA as SE_SCHEMA

        schemas = {
            "file_read": (FR_SCHEMA, "fs"),
            "file_write": (FW_SCHEMA, "fs"),
            "file_edit": (FE_SCHEMA, "fs"),
            "shell_exec": (SE_SCHEMA, "runtime"),
        }
        allow = set(self._config.tools.allow)
        deny = set(self._config.tools.deny)
        tools = []
        for name, (schema, group) in schemas.items():
            enabled = (not allow or name in allow) and name not in deny
            fn = schema.get("function", {})
            props = fn.get("parameters", {}).get("properties", {})
            required_params = fn.get("parameters", {}).get("required", [])
            tools.append({
                "name": name,
                "description": fn.get("description", ""),
                "group": group,
                "enabled": enabled,
                "params": [
                    {
                        "name": pname,
                        "type": pinfo.get("type", ""),
                        "description": pinfo.get("description", ""),
                        "required": pname in required_params,
                    }
                    for pname, pinfo in props.items()
                ],
            })
        policy = {
            "allow": list(self._config.tools.allow),
            "deny": list(self._config.tools.deny),
            "workspace_only": self._config.tools.workspace_only,
            "shell_approval_mode": self._config.tools.shell_approval_mode,
            "max_output_chars": self._config.tools.max_output_chars,
        }
        await self._send_response(
            client_id, req.id, ok=True, payload={"tools": tools, "policy": policy}
        )

    async def _handle_tools_set_policy(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Update tool policy and persist to munai.json."""
        p = req.params
        if "allow" in p:
            self._config.tools.allow = list(p["allow"])
        if "deny" in p:
            self._config.tools.deny = list(p["deny"])
        if "workspace_only" in p:
            self._config.tools.workspace_only = bool(p["workspace_only"])
        if "shell_approval_mode" in p:
            self._config.tools.shell_approval_mode = str(p["shell_approval_mode"])
        if "max_output_chars" in p:
            self._config.tools.max_output_chars = int(p["max_output_chars"])
        await self._save_config()
        await self._audit.log("tool.policy_changed", detail={"params": p})
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_approvals_list(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return all pending shell command approvals."""
        approvals = self._approval_mgr.list_pending()
        await self._send_response(
            client_id, req.id, ok=True, payload={"approvals": approvals}
        )

    async def _handle_skills_list(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return installed skills from the workspace."""
        from ..skills.loader import SkillsLoader
        skills_dir = MUNAI_DIR / "workspace" / "skills"
        manifest = SkillsLoader.scan(skills_dir)
        # Compute which required env vars are missing from ~/.munai/.env
        env_path = MUNAI_DIR / ".env"
        existing_env: set[str] = set()
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    existing_env.add(line.split("=", 1)[0].strip())
        skills_data = [
            {
                "name": s.name,
                "description": s.description,
                "trigger": s.trigger,
                "tags": s.tags,
                "file_path": str(s.file_path),
                "content": s.content,
                "required_env": s.required_env,
                "missing_env": [k for k in s.required_env if k not in existing_env],
            }
            for s in manifest.skills.values()
        ]
        await self._send_response(
            client_id, req.id, ok=True,
            payload={"skills": skills_data, "total": len(skills_data)}
        )

    async def _handle_skills_set_env(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Write an environment variable to ~/.munai/.env."""
        import re
        key = req.params.get("key", "")
        value = req.params.get("value", "")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            await self._send_response(
                client_id, req.id, ok=False,
                error=f"Invalid env key: {key!r}. Must match [A-Z][A-Z0-9_]*"
            )
            return
        env_path = MUNAI_DIR / ".env"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        # Replace existing key or append
        prefix = f"{key}="
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        await self._audit.log("skills.env_set", detail={"key": key})
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_channels_status(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return status of all channels."""
        channels = [
            {
                "id": "webchat",
                "name": "Web Chat",
                "type": "webchat",
                "enabled": True,
                "connected": True,
                "client_count": len(self._ws_connections),
            }
        ]
        if self._telegram is not None:
            tg_cfg = self._config.channels.telegram
            channels.append({
                "id": "telegram",
                "name": "Telegram",
                "type": "telegram",
                "enabled": tg_cfg.enabled,
                "connected": self._telegram.is_running(),
                "dm_policy": tg_cfg.dm_policy,
                "paired_users": len(self._pairing.get_allowed_users()),
            })
        else:
            channels.append({
                "id": "telegram",
                "name": "Telegram",
                "type": "telegram",
                "enabled": False,
                "connected": False,
                "dm_policy": None,
                "paired_users": 0,
            })
        await self._send_response(
            client_id, req.id, ok=True, payload={"channels": channels}
        )

    async def _handle_cron_list(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return scheduled heartbeat job status."""
        if self._heartbeat is None:
            await self._send_response(
                client_id, req.id, ok=True,
                payload={"jobs": [], "scheduler_running": False}
            )
            return
        status = self._heartbeat.get_status()
        scheduler_running = (
            self._heartbeat._scheduler is not None
            and self._heartbeat._scheduler.running
        )
        await self._send_response(
            client_id, req.id, ok=True,
            payload={"jobs": [status], "scheduler_running": scheduler_running}
        )

    async def _handle_cron_run_now(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Trigger the heartbeat immediately (non-blocking)."""
        if self._heartbeat is None:
            await self._send_response(
                client_id, req.id, ok=False, error="Heartbeat scheduler not running"
            )
            return
        asyncio.create_task(self._heartbeat.run_now(), name="heartbeat-manual")
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_cron_update(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Update heartbeat interval/enabled/ack_keyword and persist."""
        if self._heartbeat is None:
            await self._send_response(
                client_id, req.id, ok=False, error="Heartbeat scheduler not running"
            )
            return
        interval = req.params.get("interval_minutes")
        enabled = req.params.get("enabled")
        ack_keyword = req.params.get("ack_keyword")
        self._heartbeat.update(
            interval_minutes=int(interval) if interval is not None else None,
            enabled=bool(enabled) if enabled is not None else None,
            ack_keyword=str(ack_keyword) if ack_keyword is not None else None,
        )
        await self._save_config()
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_emergency_stop(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Toggle the emergency stop flag — abort sessions or resume."""
        self._emergency_stopped = not self._emergency_stopped
        if self._emergency_stopped:
            # Abort all running agent turns
            for event in self._abort_events.values():
                event.set()
            await self._audit.log("gateway.emergency_stop", detail={})
        else:
            await self._audit.log("gateway.emergency_resumed", detail={})
        # Broadcast to all connected clients
        event_msg = EventMessage(
            event="gateway.emergency_stopped",
            payload={"stopped": self._emergency_stopped},
        )
        for cid, ws in list(self._ws_connections.items()):
            if not ws.closed:
                try:
                    await ws.send_str(event_msg.to_json())
                except Exception:
                    pass
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_config_get(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return the current config as JSON plus a hash for concurrent-edit protection."""
        import hashlib
        payload = self._config.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True)
        config_hash = hashlib.sha256(raw.encode()).hexdigest()
        await self._send_response(
            client_id, req.id, ok=True, payload={"config": payload, "hash": config_hash}
        )

    async def _handle_config_set(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Validate and write a new config, with hash-based conflict detection."""
        import hashlib
        from ..config import Config as _Config

        incoming_hash = req.params.get("hash", "")
        new_config_dict = req.params.get("config")
        if not isinstance(new_config_dict, dict):
            await self._send_response(
                client_id, req.id, ok=False, error="'config' param must be an object"
            )
            return

        # Concurrent-edit check
        current_raw = json.dumps(self._config.model_dump(mode="json"), sort_keys=True)
        current_hash = hashlib.sha256(current_raw.encode()).hexdigest()
        if incoming_hash and incoming_hash != current_hash:
            await self._send_response(
                client_id,
                req.id,
                ok=False,
                error="Config was modified externally. Reload to see the current version.",
            )
            return

        try:
            new_config = _Config.model_validate(new_config_dict)
        except Exception as exc:
            await self._send_response(
                client_id, req.id, ok=False, error=f"Validation error: {exc}"
            )
            return

        self._config = new_config
        await self._save_config()
        await self._audit.log("config.updated", detail={})
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_doctor_run(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Run health checks and return structured results."""
        from ..cli.doctor_cmd import run_doctor_checks
        checks = run_doctor_checks()
        await self._send_response(
            client_id, req.id, ok=True, payload={"checks": checks}
        )

    async def _handle_secrets_get(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return current values for requested env var keys from ~/.munai/.env."""
        keys = req.params.get("keys", [])
        env_path = MUNAI_DIR / ".env"
        env_data: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env_data[k.strip()] = v.strip()
        values = {k: env_data.get(k, "") for k in keys}
        await self._send_response(client_id, req.id, ok=True, payload={"values": values})

    async def _handle_auth_devices_list(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return paired Telegram users and active webchat connections."""
        # Optionally generate a fresh pairing code
        if req.params.get("generate_code"):
            self._pairing.generate_code()

        allowed = self._pairing.get_allowed_users()
        pending = self._pairing.get_pending_code()
        telegram_devices = [
            {"id": uid, "type": "telegram"} for uid in allowed
        ]
        webchat_devices = [
            {"id": cid, "type": "webchat"} for cid in self._ws_connections
        ]
        await self._send_response(
            client_id,
            req.id,
            ok=True,
            payload={
                "devices": telegram_devices + webchat_devices,
                "pending_code": pending,
            },
        )

    async def _handle_auth_devices_revoke(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Revoke a device: remove from allowed list or close its WebSocket."""
        device_id = req.params.get("id", "")
        device_type = req.params.get("type", "")

        if device_type == "telegram":
            revoked = self._pairing.revoke(device_id)
            if not revoked:
                await self._send_response(
                    client_id, req.id, ok=False, error="Device not found"
                )
                return
        elif device_type == "webchat":
            ws = self._ws_connections.get(device_id)
            if ws is None:
                await self._send_response(
                    client_id, req.id, ok=False, error="Connection not found"
                )
                return
            try:
                await ws.close()
            except Exception:
                pass
        else:
            await self._send_response(
                client_id, req.id, ok=False, error=f"Unknown device type: {device_type!r}"
            )
            return

        await self._audit.log("auth.device_revoked", detail={"id": device_id, "type": device_type})
        await self._send_response(client_id, req.id, ok=True)

    async def _handle_gateway_restart(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Restart the gateway process (execv)."""
        import os
        import sys

        await self._send_response(client_id, req.id, ok=True)

        async def _do_restart() -> None:
            await asyncio.sleep(0.5)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        asyncio.create_task(_do_restart(), name="gateway-restart")

    async def _handle_send(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Send a text message to a channel — for use by external clients (e.g. Mission Control).

        Params:
            channel: ``"telegram"`` or ``"webchat"``
            to:      ``"owner"`` (all paired users / all webchat clients) or an explicit user ID
            text:    The message body to deliver
        """
        channel = req.params.get("channel", "")
        to = req.params.get("to", "owner")
        text = req.params.get("text", "")

        if not text:
            await self._send_response(
                client_id, req.id, ok=False, error="'text' param is required"
            )
            return

        sent = 0
        if channel == "telegram":
            if self._telegram is None:
                await self._send_response(
                    client_id, req.id, ok=False, error="Telegram adapter is not running"
                )
                return
            recipients = (
                self._pairing.get_allowed_users() if to == "owner" else [to]
            )
            for uid in recipients:
                try:
                    await self._telegram.send_message(uid, text)
                    sent += 1
                except Exception as exc:
                    log.warning("send: telegram delivery to %s failed: %s", uid, exc)

        elif channel == "webchat":
            event_msg = EventMessage(
                event="agent.message",
                payload={"text": text, "role": "system"},
            )
            for cid, ws in list(self._ws_connections.items()):
                if not ws.closed:
                    try:
                        await ws.send_str(event_msg.to_json())
                        sent += 1
                    except Exception:
                        pass

        else:
            await self._send_response(
                client_id, req.id, ok=False, error=f"Unknown channel: {channel!r}"
            )
            return

        await self._audit.log(
            "gateway.send",
            detail={"channel": channel, "to": to, "sent": sent},
        )
        await self._send_response(client_id, req.id, ok=True, payload={"sent": sent})

    # ─── Handlers added for webuiExpansion Phase 2-3 ─────────────────────────

    async def _handle_sessions_patch(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Store per-session overrides (model, verbose, thinking_mode)."""
        session_key = req.params.get("session_key", "")
        if not session_key:
            await self._send_response(
                client_id, req.id, ok=False, error="session_key required"
            )
            return
        overrides = req.params.get("overrides", {})
        if not isinstance(overrides, dict):
            await self._send_response(
                client_id, req.id, ok=False, error="'overrides' must be an object"
            )
            return
        # Merge into existing overrides (allows partial updates)
        current = self._session_overrides.setdefault(session_key, {})
        current.update(overrides)
        await self._send_response(
            client_id, req.id, ok=True,
            payload={"session_key": session_key, "overrides": current}
        )

    async def _handle_config_hash(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Return only the hash of the current config (no payload)."""
        import hashlib
        raw = json.dumps(self._config.model_dump(mode="json"), sort_keys=True)
        config_hash = hashlib.sha256(raw.encode()).hexdigest()
        await self._send_response(
            client_id, req.id, ok=True, payload={"hash": config_hash}
        )

    async def _handle_skills_install(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Install a skill from a local path or git URL."""
        source = req.params.get("source", "").strip()
        if not source:
            await self._send_response(
                client_id, req.id, ok=False, error="'source' param is required"
            )
            return

        skills_dir = MUNAI_DIR / "workspace" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        is_url = source.startswith(("http://", "https://", "git@", "git://"))
        if is_url:
            # Derive name from URL: last path component without .git
            name = source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            dest = skills_dir / name
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth=1", source, str(dest),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace").strip()[:300]
                await self._send_response(
                    client_id, req.id, ok=False,
                    error=f"git clone failed: {err}"
                )
                return
        else:
            src_path = Path(source).expanduser().resolve()
            if not src_path.exists():
                await self._send_response(
                    client_id, req.id, ok=False,
                    error=f"Path not found: {source}"
                )
                return
            name = src_path.name
            dest = skills_dir / name
            if dest.exists():
                await self._send_response(
                    client_id, req.id, ok=False,
                    error=f"Skill '{name}' already installed. Remove it first."
                )
                return
            import shutil
            if src_path.is_dir():
                shutil.copytree(str(src_path), str(dest))
            else:
                # Single file: treat as SKILL.md directly
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_path), str(dest / "SKILL.md"))

        # Validate SKILL.md exists
        skill_md = dest / "SKILL.md"
        if not skill_md.exists():
            import shutil
            shutil.rmtree(str(dest), ignore_errors=True)
            await self._send_response(
                client_id, req.id, ok=False,
                error=f"No SKILL.md found in '{name}'. Skill not installed."
            )
            return

        await self._audit.log("skills.install", detail={"name": name, "source": source})
        await self._send_response(
            client_id, req.id, ok=True,
            payload={"name": name, "path": str(dest)}
        )

    async def _handle_cron_create(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Create a new custom scheduled job."""
        import uuid as _uuid
        name = req.params.get("name", "").strip()
        interval_minutes = req.params.get("interval_minutes")
        prompt = req.params.get("prompt", "").strip()
        model = req.params.get("model")
        delivery = req.params.get("delivery", "suppress_ok")

        if not name:
            await self._send_response(
                client_id, req.id, ok=False, error="'name' required"
            )
            return
        if not prompt:
            await self._send_response(
                client_id, req.id, ok=False, error="'prompt' required"
            )
            return
        try:
            interval_minutes = int(interval_minutes or 60)
            if interval_minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            await self._send_response(
                client_id, req.id, ok=False,
                error="'interval_minutes' must be a positive integer"
            )
            return

        job_id = str(_uuid.uuid4())[:8]
        job: dict = {
            "id": job_id,
            "name": name,
            "interval_minutes": interval_minutes,
            "prompt": prompt,
            "model": model,
            "delivery": delivery,
            "enabled": True,
        }
        self._custom_jobs[job_id] = job
        self._save_custom_jobs()

        # Schedule in APScheduler if heartbeat scheduler is running
        if self._heartbeat and self._heartbeat._scheduler and self._heartbeat._scheduler.running:
            async def run_custom_job(j: dict = job) -> None:
                session_id = self._session_router.get_or_create_session(
                    f"cron:{j['id']}"
                )
                async def _noop_emit(_event_name: str, _payload: dict) -> None:
                    pass
                try:
                    response = await self._agent.run_turn(
                        session_id=session_id,
                        channel="cron",
                        sender_id="scheduler",
                        text=j["prompt"],
                        emit=_noop_emit,
                    )
                    ack = self._config.heartbeat.ack_keyword
                    if j["delivery"] != "suppress_ok" or not (ack and ack in response):
                        log.info("Cron job '%s' response: %s", j["name"], response[:100])
                except Exception as exc:
                    log.error("Cron job '%s' failed: %s", j["name"], exc)

            self._heartbeat._scheduler.add_job(
                run_custom_job,
                "interval",
                id=job_id,
                minutes=interval_minutes,
                name=name,
            )

        await self._audit.log("cron.created", detail={"job_id": job_id, "name": name})
        await self._send_response(
            client_id, req.id, ok=True, payload={"job": job}
        )

    async def _handle_cron_delete(
        self, client_id: str, req: RequestMessage
    ) -> None:
        """Delete a custom scheduled job (cannot delete the built-in heartbeat)."""
        job_id = req.params.get("job_id", "").strip()
        if not job_id:
            await self._send_response(
                client_id, req.id, ok=False, error="'job_id' required"
            )
            return
        if job_id == "heartbeat":
            await self._send_response(
                client_id, req.id, ok=False,
                error="The built-in heartbeat job cannot be deleted. Use cron.update to disable it."
            )
            return
        if job_id not in self._custom_jobs:
            await self._send_response(
                client_id, req.id, ok=False,
                error=f"Job '{job_id}' not found"
            )
            return

        del self._custom_jobs[job_id]
        self._save_custom_jobs()

        if self._heartbeat and self._heartbeat._scheduler:
            try:
                self._heartbeat._scheduler.remove_job(job_id)
            except Exception:
                pass  # Job may not be scheduled if scheduler was restarted

        await self._audit.log("cron.deleted", detail={"job_id": job_id})
        await self._send_response(client_id, req.id, ok=True)

    # ─── Custom cron persistence helpers ─────────────────────────────────────

    def _load_custom_jobs(self) -> dict[str, dict]:
        path = MUNAI_DIR / "cron.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_custom_jobs(self) -> None:
        path = MUNAI_DIR / "cron.json"
        MUNAI_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._custom_jobs, indent=2), encoding="utf-8")

    async def _save_config(self) -> None:
        """Persist the current in-memory config to munai.json."""
        config_path = MUNAI_DIR / "munai.json"
        config_path.write_text(
            json.dumps(self._config.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    # ─── Outbound helpers ────────────────────────────────────────────────────

    async def _send_response(
        self,
        client_id: str,
        request_id: str,
        ok: bool,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        ws = self._ws_connections.get(client_id)
        if ws is None or ws.closed:
            return
        msg = ResponseMessage(id=request_id, ok=ok, payload=payload or {}, error=error)
        try:
            await ws.send_str(msg.to_json())
        except Exception as exc:
            log.debug("Failed to send response to %s: %s", client_id, exc)

    async def _emit(
        self,
        client_id: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        ws = self._ws_connections.get(client_id)
        if ws is None or ws.closed:
            return
        seq = self._ws_seq.get(client_id, 0) + 1
        self._ws_seq[client_id] = seq
        event = EventMessage(event=event_name, payload=payload, seq=seq)
        try:
            await ws.send_str(event.to_json())
        except Exception as exc:
            log.debug("Failed to emit %s to %s: %s", event_name, client_id, exc)
