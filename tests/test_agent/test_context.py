"""Tests for context assembly (system prompt building + session history conversion)."""
from __future__ import annotations

from pathlib import Path

import pytest

from munai.agent.context import ContextAssembler
from munai.config import AgentConfig


@pytest.fixture
def config(tmp_workspace: Path) -> AgentConfig:
    return AgentConfig(workspace=str(tmp_workspace))


@pytest.fixture
def assembler(config: AgentConfig) -> ContextAssembler:
    return ContextAssembler(config)


def test_missing_files_inject_markers(assembler: ContextAssembler):
    """Workspace with no files → each missing file gets a [FILE: not configured] marker."""
    system_prompt, _ = assembler.assemble([])
    assert "[AGENTS.md: not configured]" in system_prompt
    assert "[SOUL.md: not configured]" in system_prompt
    assert "[USER.md: not configured]" in system_prompt


def test_existing_file_injected(assembler: ContextAssembler, tmp_workspace: Path):
    (tmp_workspace / "SOUL.md").write_text("Be helpful.", encoding="utf-8")
    system_prompt, _ = assembler.assemble([])
    assert "Be helpful." in system_prompt
    assert "--- SOUL.md ---" in system_prompt


def test_injection_order(assembler: ContextAssembler, tmp_workspace: Path):
    """AGENTS.md must appear before SOUL.md in the system prompt."""
    (tmp_workspace / "AGENTS.md").write_text("AGENTS content", encoding="utf-8")
    (tmp_workspace / "SOUL.md").write_text("SOUL content", encoding="utf-8")
    system_prompt, _ = assembler.assemble([])
    agents_pos = system_prompt.find("AGENTS content")
    soul_pos = system_prompt.find("SOUL content")
    assert agents_pos < soul_pos, "AGENTS.md should appear before SOUL.md"


def test_truncation_at_char_limit(assembler: ContextAssembler, tmp_workspace: Path):
    """Files exceeding bootstrap_max_chars are truncated."""
    big_content = "X" * (assembler._config.bootstrap_max_chars + 1000)
    (tmp_workspace / "AGENTS.md").write_text(big_content, encoding="utf-8")
    system_prompt, _ = assembler.assemble([])
    assert "[... truncated]" in system_prompt


def test_session_history_to_messages(assembler: ContextAssembler):
    """User and assistant events are converted to role/content dicts."""
    history = [
        {"type": "user", "text": "Hello"},
        {"type": "assistant", "text": "Hi there"},
        {"type": "user", "text": "How are you?"},
    ]
    _, messages = assembler.assemble(history)
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "Hello"}
    assert messages[1] == {"role": "assistant", "content": "Hi there"}
    assert messages[2] == {"role": "user", "content": "How are you?"}


def test_unknown_event_types_skipped(assembler: ContextAssembler):
    """tool_call and compaction events are ignored in Phase 1."""
    history = [
        {"type": "user", "text": "run a tool"},
        {"type": "tool_call", "tool": "file_read", "params": {}},
        {"type": "tool_result", "success": True, "output": "content"},
        {"type": "assistant", "text": "Done."},
    ]
    _, messages = assembler.assemble(history)
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]


def test_memory_md_injected_if_exists(assembler: ContextAssembler, tmp_workspace: Path):
    (tmp_workspace / "MEMORY.md").write_text("Remember: user likes cats.", encoding="utf-8")
    system_prompt, _ = assembler.assemble([])
    assert "user likes cats" in system_prompt


def test_base_prompt_always_present(assembler: ContextAssembler):
    system_prompt, _ = assembler.assemble([])
    assert "Munai" in system_prompt
    assert "Safety Constraints" in system_prompt
