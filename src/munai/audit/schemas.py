"""Pydantic models and event type constants for audit log events.

Public API (importable by external consumers such as Mission Control):

    from munai.audit.schemas import AuditEvent
"""
from __future__ import annotations

__all__ = [
    "AuditEvent",
    "EVENT_MODEL_CALL",
    "EVENT_MODEL_FAILOVER",
]

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

# ── Event type constants ───────────────────────────────────────────────────────
# Add new event types here as the system grows.

EVENT_MODEL_CALL = "agent.model_call"
EVENT_MODEL_FAILOVER = "agent.model_failover"


class AuditEvent(BaseModel):
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    event_type: str
    session_id: str | None = None
    channel: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None

    def to_jsonl_line(self) -> str:
        return self.model_dump_json() + "\n"
