"""Tests for HeartbeatScheduler."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from munai.config import (
    AgentConfig,
    ApiFormat,
    AuditConfig,
    ChannelsConfig,
    Config,
    GatewayConfig,
    HeartbeatConfig,
    ModelsConfig,
    ProviderConfig,
    ToolsConfig,
)
from munai.scheduler.heartbeat import HeartbeatScheduler


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_config(tmp_workspace: Path, interval: int = 30, ack_keyword: str = "HEARTBEAT_OK") -> Config:
    return Config(
        models=ModelsConfig(
            primary="anthropic",
            providers={
                "anthropic": ProviderConfig(
                    name="anthropic",
                    base_url="https://api.anthropic.com/v1",
                    api_format=ApiFormat.ANTHROPIC,
                    api_key_env="ANTHROPIC_API_KEY",
                    api_key_header="x-api-key",
                    api_key_prefix="",
                    model="claude-test",
                )
            },
        ),
        agent=AgentConfig(workspace=str(tmp_workspace)),
        heartbeat=HeartbeatConfig(enabled=True, interval_minutes=interval, ack_keyword=ack_keyword),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def config(workspace: Path) -> Config:
    return _make_config(workspace)


def _make_scheduler(
    config: Config,
    runtime=None,
    telegram=None,
    pairing=None,
    session_manager=None,
    session_router=None,
    audit=None,
) -> HeartbeatScheduler:
    if runtime is None:
        runtime = MagicMock()
        runtime.run_turn = AsyncMock(return_value="response text")
    if pairing is None:
        pairing = MagicMock()
        pairing.get_allowed_users = MagicMock(return_value=[])
    if session_manager is None:
        session_manager = MagicMock()
    if session_router is None:
        session_router = MagicMock()
        session_router.get_or_create_session = MagicMock(return_value="heartbeat-sess-id")
    if audit is None:
        audit = MagicMock()
        audit.log = AsyncMock()

    return HeartbeatScheduler(
        config=config,
        runtime=runtime,
        telegram=telegram,
        pairing=pairing,
        session_manager=session_manager,
        session_router=session_router,
        audit=audit,
    )


# ─── _read_heartbeat_md ───────────────────────────────────────────────────────

def test_read_heartbeat_md_returns_content(workspace: Path, config: Config):
    (workspace / "HEARTBEAT.md").write_text("## Tasks\n- Check email\n", encoding="utf-8")
    scheduler = _make_scheduler(config)
    content = scheduler._read_heartbeat_md()
    assert "Check email" in content


def test_read_heartbeat_md_returns_empty_for_missing(workspace: Path, config: Config):
    scheduler = _make_scheduler(config)
    assert scheduler._read_heartbeat_md() == ""


def test_read_heartbeat_md_returns_empty_for_whitespace_only(workspace: Path, config: Config):
    (workspace / "HEARTBEAT.md").write_text("   \n\n   ", encoding="utf-8")
    scheduler = _make_scheduler(config)
    assert scheduler._read_heartbeat_md() == ""


def test_read_heartbeat_md_returns_empty_for_comments_only(workspace: Path, config: Config):
    (workspace / "HEARTBEAT.md").write_text(
        "# HEARTBEAT.md — Proactive Task Checklist\n# (none configured)\n",
        encoding="utf-8",
    )
    scheduler = _make_scheduler(config)
    assert scheduler._read_heartbeat_md() == ""


# ─── _run_heartbeat ───────────────────────────────────────────────────────────

async def test_heartbeat_skips_empty_heartbeat_md(workspace: Path, config: Config):
    """Empty HEARTBEAT.md should skip the agent call entirely."""
    runtime = MagicMock()
    runtime.run_turn = AsyncMock()
    scheduler = _make_scheduler(config, runtime=runtime)
    await scheduler._run_heartbeat()
    runtime.run_turn.assert_not_called()


async def test_heartbeat_calls_agent_with_heartbeat_content(workspace: Path, config: Config):
    """When HEARTBEAT.md has content, the agent should be called."""
    (workspace / "HEARTBEAT.md").write_text("- Check disk usage\n", encoding="utf-8")

    captured: dict = {}

    async def mock_run_turn(session_id, channel, sender_id, text, emit):
        captured["text"] = text
        await emit("agent.done", {"text": "disk usage is 40%"})

    runtime = MagicMock()
    runtime.run_turn = mock_run_turn
    runtime.run_turn = AsyncMock(side_effect=mock_run_turn)
    scheduler = _make_scheduler(config, runtime=runtime)
    await scheduler._run_heartbeat()

    assert "HEARTBEAT RUN" in captured["text"]
    assert "disk usage" in captured["text"]


async def test_heartbeat_ok_suppresses_telegram_send(workspace: Path, config: Config):
    """Response containing ack keyword should NOT be forwarded to Telegram."""
    (workspace / "HEARTBEAT.md").write_text("- Status check\n", encoding="utf-8")

    async def mock_run_turn(session_id, channel, sender_id, text, emit):
        await emit("agent.done", {"text": "All good. HEARTBEAT_OK"})

    runtime = MagicMock()
    runtime.run_turn = AsyncMock(side_effect=mock_run_turn)

    telegram = MagicMock()
    telegram.send_message = AsyncMock()

    pairing = MagicMock()
    pairing.get_allowed_users = MagicMock(return_value=["12345"])

    audit = MagicMock()
    audit.log = AsyncMock()

    scheduler = _make_scheduler(config, runtime=runtime, telegram=telegram, pairing=pairing, audit=audit)
    await scheduler._run_heartbeat()

    telegram.send_message.assert_not_called()


async def test_heartbeat_never_forwards_to_telegram(workspace: Path, config: Config):
    """Heartbeat responses are never forwarded to Telegram — they stay in their own session."""
    (workspace / "HEARTBEAT.md").write_text("- Check logs\n", encoding="utf-8")

    async def mock_run_turn(session_id, channel, sender_id, text, emit):
        await emit("agent.done", {"text": "Found 3 errors in logs."})

    runtime = MagicMock()
    runtime.run_turn = AsyncMock(side_effect=mock_run_turn)

    telegram = MagicMock()
    telegram.send_message = AsyncMock()

    pairing = MagicMock()
    pairing.get_allowed_users = MagicMock(return_value=["111", "222"])

    audit = MagicMock()
    audit.log = AsyncMock()

    scheduler = _make_scheduler(config, runtime=runtime, telegram=telegram, pairing=pairing, audit=audit)
    await scheduler._run_heartbeat()

    telegram.send_message.assert_not_called()


async def test_heartbeat_logs_to_audit(workspace: Path, config: Config):
    (workspace / "HEARTBEAT.md").write_text("- Task\n", encoding="utf-8")

    async def mock_run_turn(session_id, channel, sender_id, text, emit):
        await emit("agent.done", {"text": "Done. HEARTBEAT_OK"})

    runtime = MagicMock()
    runtime.run_turn = AsyncMock(side_effect=mock_run_turn)
    audit = MagicMock()
    audit.log = AsyncMock()

    scheduler = _make_scheduler(config, runtime=runtime, audit=audit)
    await scheduler._run_heartbeat()

    logged_events = [c.args[0] for c in audit.log.call_args_list]
    assert "heartbeat.run" in logged_events


async def test_heartbeat_no_telegram_no_error(workspace: Path, config: Config):
    """When telegram is None, heartbeat should still run without error."""
    (workspace / "HEARTBEAT.md").write_text("- Task\n", encoding="utf-8")

    async def mock_run_turn(session_id, channel, sender_id, text, emit):
        await emit("agent.done", {"text": "Result without HEARTBEAT_OK"})

    runtime = MagicMock()
    runtime.run_turn = AsyncMock(side_effect=mock_run_turn)
    audit = MagicMock()
    audit.log = AsyncMock()

    scheduler = _make_scheduler(config, runtime=runtime, telegram=None, audit=audit)
    # Should not raise
    await scheduler._run_heartbeat()
