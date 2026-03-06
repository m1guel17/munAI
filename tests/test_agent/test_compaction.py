"""Tests for session compaction (Compactor + apply_compaction)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from munai.agent.compaction import Compactor, apply_compaction, COMPACTION_BATCH_TURNS


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}


def _assistant(text: str) -> dict[str, Any]:
    return {"type": "assistant", "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}


def _make_history(n_pairs: int) -> list[dict[str, Any]]:
    """Generate n_pairs of user/assistant turns."""
    history = []
    for i in range(n_pairs):
        history.append(_user(f"User message {i}"))
        history.append(_assistant(f"Assistant reply {i}"))
    return history


def _mock_resolver() -> MagicMock:
    """Return a ModelResolver mock. Compaction uses llm_client.generate (patched per test)."""
    resolver = MagicMock()
    mock_provider = MagicMock()
    mock_provider.timeout_seconds = 60
    resolver.get_client.return_value = (MagicMock(), "test-model", mock_provider)
    return resolver


# ─── apply_compaction ────────────────────────────────────────────────────────

def test_apply_compaction_removes_oldest_turns():
    history = _make_history(5)  # 10 events total
    new_history, event = apply_compaction(history, "summary text", 4, "sess-1")
    # 4 turns removed → 6 remain, plus 1 compaction event prepended
    user_assistant_remaining = [e for e in new_history if e["type"] in ("user", "assistant")]
    assert len(user_assistant_remaining) == 10 - 4


def test_apply_compaction_prepends_compaction_event():
    history = _make_history(3)
    new_history, event = apply_compaction(history, "summary", 2, "sess-1")
    assert new_history[0]["type"] == "compaction"
    assert new_history[0]["summary"] == "summary"


def test_apply_compaction_event_has_turns_compacted():
    history = _make_history(4)
    _, event = apply_compaction(history, "my summary", 6, "sess-1")
    # Only 8 turns exist (4 pairs), so at most 8 can be removed
    assert event["turns_compacted"] <= 8
    assert event["summary"] == "my summary"


def test_apply_compaction_preserves_non_conversation_events():
    history = [
        {"type": "system", "text": "system event"},
        _user("hello"),
        _assistant("hi"),
    ]
    new_history, _ = apply_compaction(history, "sum", 2, "sess-1")
    types = [e["type"] for e in new_history]
    assert "system" in types  # system events are not counted as user/assistant


def test_apply_compaction_full_removal():
    history = _make_history(2)  # 4 events
    new_history, event = apply_compaction(history, "sum", 4, "sess-1")
    remaining = [e for e in new_history if e["type"] in ("user", "assistant")]
    assert len(remaining) == 0
    assert new_history[0]["type"] == "compaction"


def test_apply_compaction_timestamp_is_set():
    history = _make_history(2)
    _, event = apply_compaction(history, "sum", 2, "sess-1")
    assert "timestamp" in event
    # Should be a valid ISO timestamp
    datetime.fromisoformat(event["timestamp"])


# ─── Compactor.compact ───────────────────────────────────────────────────────

async def test_compact_empty_history_returns_zero():
    resolver = _mock_resolver()
    compactor = Compactor(resolver)
    summary, count = await compactor.compact([])
    assert summary == ""
    assert count == 0


async def test_compact_returns_batch_count():
    resolver = _mock_resolver()
    compactor = Compactor(resolver)

    history = _make_history(8)  # 16 turns

    with patch("munai.agent.compaction.llm_client") as mock_llm:
        mock_llm.generate = AsyncMock(return_value="Summarized conversation.")

        summary, count = await compactor.compact(history, batch_size=4)

    assert count == 4
    assert "Summarized" in summary


async def test_compact_respects_batch_size():
    resolver = _mock_resolver()
    compactor = Compactor(resolver)
    history = _make_history(10)

    with patch("munai.agent.compaction.llm_client") as mock_llm:
        mock_llm.generate = AsyncMock(return_value="Summary.")

        _, count = await compactor.compact(history, batch_size=6)

    assert count == 6


async def test_compact_fallback_on_llm_failure():
    resolver = _mock_resolver()
    compactor = Compactor(resolver)
    history = _make_history(3)

    with patch("munai.agent.compaction.llm_client") as mock_llm:
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM offline"))

        summary, count = await compactor.compact(history, batch_size=4)

    # Should return fallback summary rather than raising
    assert count > 0
    assert "Compaction failed" in summary or count <= 6


async def test_compact_includes_all_batch_turns_in_transcript():
    """Verify the transcript passed to the LLM contains the batch turns."""
    resolver = _mock_resolver()
    compactor = Compactor(resolver)
    history = [
        _user("What is the capital of France?"),
        _assistant("Paris."),
        _user("And Germany?"),
        _assistant("Berlin."),
    ]

    captured_prompt = {}

    async def capture_generate(client, model, messages, *, system=None, timeout=60.0):
        captured_prompt["text"] = messages[0]["content"] if messages else ""
        return "Discussed capitals."

    with patch("munai.agent.compaction.llm_client") as mock_llm:
        mock_llm.generate = capture_generate

        await compactor.compact(history, batch_size=4)

    assert "France" in captured_prompt.get("text", "")
    assert "Berlin" in captured_prompt.get("text", "")


# ─── Integration: compact + apply ────────────────────────────────────────────

async def test_compact_then_apply_produces_valid_history():
    resolver = _mock_resolver()
    compactor = Compactor(resolver)
    history = _make_history(6)  # 12 events

    with patch("munai.agent.compaction.llm_client") as mock_llm:
        mock_llm.generate = AsyncMock(return_value="Discussed 3 topics.")

        summary, count = await compactor.compact(history, batch_size=4)

    new_history, event = apply_compaction(history, summary, count, "sess-x")

    assert new_history[0]["type"] == "compaction"
    assert new_history[0]["summary"] == "Discussed 3 topics."
    assert event["turns_compacted"] == count
