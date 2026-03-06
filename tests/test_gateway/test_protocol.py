"""Tests for gateway WebSocket protocol parsing."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from munai.gateway.protocol import (
    ConnectMessage,
    RequestMessage,
    parse_inbound,
)


def test_parse_connect_valid():
    raw = json.dumps({
        "type": "connect",
        "client_id": "abc-123",
        "client_type": "webchat",
        "auth": {"token": None},
    })
    msg = parse_inbound(raw)
    assert isinstance(msg, ConnectMessage)
    assert msg.client_id == "abc-123"
    assert msg.client_type == "webchat"
    assert msg.auth.token is None


def test_parse_connect_with_token():
    raw = json.dumps({
        "type": "connect",
        "client_id": "abc-123",
        "client_type": "cli",
        "auth": {"token": "secret"},
    })
    msg = parse_inbound(raw)
    assert isinstance(msg, ConnectMessage)
    assert msg.auth.token == "secret"


def test_parse_req_valid():
    raw = json.dumps({
        "type": "req",
        "id": "req-001",
        "method": "agent",
        "params": {"text": "hello"},
        "idempotency_key": "ik_abc",
    })
    msg = parse_inbound(raw)
    assert isinstance(msg, RequestMessage)
    assert msg.method == "agent"
    assert msg.params["text"] == "hello"
    assert msg.idempotency_key == "ik_abc"


def test_parse_req_defaults():
    """id is optional (auto-generated) and params defaults to {}."""
    raw = json.dumps({"type": "req", "method": "health"})
    msg = parse_inbound(raw)
    assert isinstance(msg, RequestMessage)
    assert msg.id  # auto-generated UUID
    assert msg.params == {}


def test_parse_unknown_type_raises():
    raw = json.dumps({"type": "subscribe", "channel": "events"})
    with pytest.raises(ValueError, match="Unknown message type"):
        parse_inbound(raw)


def test_parse_malformed_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_inbound("{not json}")


def test_parse_non_object_raises():
    with pytest.raises(ValueError, match="JSON object"):
        parse_inbound("[1, 2, 3]")


def test_parse_invalid_connect_raises():
    """client_type must be one of the literal values."""
    raw = json.dumps({
        "type": "connect",
        "client_id": "x",
        "client_type": "unknown_type",
    })
    with pytest.raises((ValueError, ValidationError)):
        parse_inbound(raw)


def test_response_to_json():
    from munai.gateway.protocol import ResponseMessage
    msg = ResponseMessage(id="req-1", ok=True, payload={"status": "ok"})
    data = json.loads(msg.to_json())
    assert data["type"] == "res"
    assert data["ok"] is True
    assert data["payload"]["status"] == "ok"


def test_event_to_json():
    from munai.gateway.protocol import EventMessage
    msg = EventMessage(event="agent.delta", payload={"text": "hello"}, seq=5)
    data = json.loads(msg.to_json())
    assert data["type"] == "event"
    assert data["event"] == "agent.delta"
    assert data["seq"] == 5
