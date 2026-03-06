"""Tests for JSONL session persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from munai.agent.session import SessionManager


@pytest.fixture
def session_mgr(tmp_path: Path) -> SessionManager:
    return SessionManager(sessions_dir=tmp_path / "sessions")


async def test_load_missing_session_returns_empty(session_mgr: SessionManager):
    result = await session_mgr.load("nonexistent-session-id")
    assert result == []


async def test_append_and_load(session_mgr: SessionManager):
    sid = "test-session-1"
    event1 = {"type": "user", "text": "hello", "timestamp": "2026-01-01T00:00:00Z"}
    event2 = {"type": "assistant", "text": "hi there", "timestamp": "2026-01-01T00:00:01Z"}

    await session_mgr.append(sid, event1)
    await session_mgr.append(sid, event2)

    events = await session_mgr.load(sid)
    assert len(events) == 2
    assert events[0]["type"] == "user"
    assert events[0]["text"] == "hello"
    assert events[1]["type"] == "assistant"


async def test_append_preserves_order(session_mgr: SessionManager):
    sid = "test-order"
    for i in range(5):
        await session_mgr.append(sid, {"type": "user", "n": i})

    events = await session_mgr.load(sid)
    assert len(events) == 5
    for i, e in enumerate(events):
        assert e["n"] == i


async def test_append_creates_directory(tmp_path: Path):
    nested = tmp_path / "deep" / "nested" / "sessions"
    mgr = SessionManager(sessions_dir=nested)
    await mgr.append("sess-1", {"type": "user", "text": "x"})
    assert (nested / "sess-1.jsonl").exists()


async def test_multiple_sessions_independent(session_mgr: SessionManager):
    await session_mgr.append("sess-a", {"type": "user", "text": "A"})
    await session_mgr.append("sess-b", {"type": "user", "text": "B"})

    a = await session_mgr.load("sess-a")
    b = await session_mgr.load("sess-b")

    assert len(a) == 1 and a[0]["text"] == "A"
    assert len(b) == 1 and b[0]["text"] == "B"
