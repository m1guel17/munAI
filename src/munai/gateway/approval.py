"""Shell command approval manager — pause/resume via asyncio.Future."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


class ApprovalManager:
    """Manages pending shell command approvals.

    When shell_exec needs approval, it:
    1. Calls request_approval() — creates a Future, stores it, emits an event.
    2. Awaits the Future (blocking the tool coroutine but not the event loop).
    3. The WebSocket handler calls approve() or deny() to resolve the Future.
    4. shell_exec resumes with True (approved) or False (denied).

    This works because everything runs in the same asyncio event loop:
    the Future can be resolved by a different coroutine (the WS handler)
    while shell_exec awaits it.
    """

    def __init__(self) -> None:
        # approval_id → asyncio.Future[bool]
        self._pending: dict[str, asyncio.Future[bool]] = {}
        # approval_id → metadata for list_pending()
        self._metadata: dict[str, dict[str, Any]] = {}

    async def request_approval(
        self,
        approval_id: str,
        command: list[str],
        session_id: str,
        emit_fn: Any,  # EmitFn: async (event_name, payload) -> None
    ) -> bool:
        """Register a pending approval and wait for the user's decision.

        Emits a ``tool.approval_requested`` event to the client, then blocks
        until approve() or deny() is called with the same approval_id.

        Returns True if approved, False if denied or timed out.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future
        self._metadata[approval_id] = {
            "command": command,
            "session_id": session_id,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }

        await emit_fn("tool.approval_requested", {
            "approval_id": approval_id,
            "command": command,
            "session_id": session_id,
        })

        try:
            # Wait up to 5 minutes for user response; default to denied on timeout
            return await asyncio.wait_for(asyncio.shield(future), timeout=300)
        except asyncio.TimeoutError:
            log.warning("Approval request %s timed out", approval_id)
            return False
        finally:
            self._pending.pop(approval_id, None)
            self._metadata.pop(approval_id, None)

    def approve(self, approval_id: str) -> bool:
        """Resolve a pending approval as approved.

        Returns True if the approval_id was found, False if it had already expired.
        """
        future = self._pending.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result(True)
        return True

    def deny(self, approval_id: str) -> bool:
        """Resolve a pending approval as denied.

        Returns True if the approval_id was found, False if it had already expired.
        """
        future = self._pending.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result(False)
        return True

    def pending_approvals(self) -> list[str]:
        """Return IDs of all currently pending approvals."""
        return list(self._pending.keys())

    def list_pending(self) -> list[dict[str, Any]]:
        """Return metadata for all pending approvals."""
        result = []
        for approval_id, meta in self._metadata.items():
            if approval_id in self._pending:
                result.append({"approval_id": approval_id, **meta})
        return result
