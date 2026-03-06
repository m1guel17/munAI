"""WebSocket message schemas and frame parser for the munAI Gateway."""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── Inbound: Client → Server ────────────────────────────────────────────────

class AuthPayload(BaseModel):
    token: str | None = None


class ConnectMessage(BaseModel):
    type: Literal["connect"]
    client_id: str
    client_type: Literal["webchat", "cli", "channel_adapter", "external_app"]
    auth: AuthPayload = Field(default_factory=AuthPayload)


class RequestMessage(BaseModel):
    type: Literal["req"]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


# ─── Outbound: Server → Client ───────────────────────────────────────────────

class ResponseMessage(BaseModel):
    type: Literal["res"] = "res"
    id: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    def to_json(self) -> str:
        return self.model_dump_json()


class EventMessage(BaseModel):
    type: Literal["event"] = "event"
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    seq: int = 0

    def to_json(self) -> str:
        return self.model_dump_json()


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_inbound(raw: str) -> ConnectMessage | RequestMessage:
    """Parse a raw JSON WebSocket frame into a typed message.

    Raises:
        ValueError: if the frame is not valid JSON, missing a ``type`` field,
                    or has an unrecognized type.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Frame is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Frame must be a JSON object")

    msg_type = data.get("type")
    if msg_type == "connect":
        return ConnectMessage.model_validate(data)
    if msg_type == "req":
        return RequestMessage.model_validate(data)
    raise ValueError(f"Unknown message type: {msg_type!r}")
