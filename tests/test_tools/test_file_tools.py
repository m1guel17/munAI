"""Tests for file_read, file_write, and file_edit tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from munai.config import ToolsConfig
from munai.tools.base import ToolDeps
from munai.tools.policy import ToolPolicyEnforcer
from munai.tools.sandbox import PathSandbox


# ─── Fixtures ────────────────────────────────────────────────────────────────



@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def deps(workspace: Path) -> ToolDeps:
    sandbox = PathSandbox(workspace)
    policy = ToolPolicyEnforcer(ToolsConfig())
    audit = AsyncMock()
    audit.log = AsyncMock()
    emit = AsyncMock()
    return ToolDeps(
        workspace_path=workspace,
        sandbox=sandbox,
        policy=policy,
        audit=audit,
        session_id="test-session",
        channel="test",
        emit=emit,
        request_approval=AsyncMock(return_value=True),
    )


# ─── file_read tests ─────────────────────────────────────────────────────────

async def test_file_read_existing(deps: ToolDeps, workspace: Path):
    from munai.tools.file_read import file_read
    (workspace / "hello.txt").write_text("Hello, world!", encoding="utf-8")
    result = await file_read(deps, "hello.txt")
    assert "Hello, world!" in result


async def test_file_read_missing(deps: ToolDeps):
    from munai.tools.file_read import file_read
    result = await file_read(deps, "nonexistent.txt")
    assert "not found" in result.lower() or "Error" in result


async def test_file_read_line_range(deps: ToolDeps, workspace: Path):
    from munai.tools.file_read import file_read
    lines = "\n".join(f"line {i}" for i in range(1, 11))
    (workspace / "lines.txt").write_text(lines, encoding="utf-8")
    result = await file_read(deps, "lines.txt", line_start=3, line_end=5)
    assert "line 3" in result
    assert "line 5" in result
    assert "line 1" not in result
    assert "line 6" not in result


async def test_file_read_path_traversal_blocked(deps: ToolDeps):
    from munai.tools.file_read import file_read
    result = await file_read(deps, "../../etc/passwd")
    assert "Permission" in result or "outside" in result.lower()


# ─── file_write tests ────────────────────────────────────────────────────────

async def test_file_write_creates_file(deps: ToolDeps, workspace: Path):
    from munai.tools.file_write import file_write
    result = await file_write(deps, "new_file.txt", "content here")
    assert "written" in result.lower() or "File" in result
    assert (workspace / "new_file.txt").read_text() == "content here"


async def test_file_write_overwrites(deps: ToolDeps, workspace: Path):
    from munai.tools.file_write import file_write
    (workspace / "existing.txt").write_text("old")
    await file_write(deps, "existing.txt", "new content")
    assert (workspace / "existing.txt").read_text() == "new content"


async def test_file_write_creates_subdirectory(deps: ToolDeps, workspace: Path):
    from munai.tools.file_write import file_write
    await file_write(deps, "subdir/nested.txt", "hello")
    assert (workspace / "subdir" / "nested.txt").exists()


async def test_file_write_traversal_blocked(deps: ToolDeps):
    from munai.tools.file_write import file_write
    result = await file_write(deps, "../../malicious.txt", "hack")
    assert "Permission" in result or "outside" in result.lower()


# ─── file_edit tests ─────────────────────────────────────────────────────────

async def test_file_edit_success(deps: ToolDeps, workspace: Path):
    from munai.tools.file_edit import file_edit
    (workspace / "doc.txt").write_text("Hello World!")
    result = await file_edit(deps, "doc.txt", "World", "Python")
    assert "Edit applied" in result or "applied" in result.lower()
    assert (workspace / "doc.txt").read_text() == "Hello Python!"


async def test_file_edit_not_found_raises(deps: ToolDeps):
    from munai.tools.file_edit import file_edit
    result = await file_edit(deps, "missing.txt", "old", "new")
    assert "not found" in result.lower() or "Error" in result


async def test_file_edit_old_text_missing(deps: ToolDeps, workspace: Path):
    from munai.tools.file_edit import file_edit
    (workspace / "doc.txt").write_text("content")
    result = await file_edit(deps, "doc.txt", "NOTPRESENT", "replacement")
    assert "not found" in result.lower()


async def test_file_edit_ambiguous_text(deps: ToolDeps, workspace: Path):
    from munai.tools.file_edit import file_edit
    (workspace / "doc.txt").write_text("foo foo foo")
    result = await file_edit(deps, "doc.txt", "foo", "bar")
    # Should fail because "foo" appears multiple times
    assert "times" in result or "unique" in result.lower()
    # File should be unchanged
    assert (workspace / "doc.txt").read_text() == "foo foo foo"


# ─── Audit logging ───────────────────────────────────────────────────────────

async def test_file_read_logs_to_audit(deps: ToolDeps, workspace: Path):
    from munai.tools.file_read import file_read
    (workspace / "test.txt").write_text("data")
    await file_read(deps, "test.txt")
    # Both tool.call and tool.result should be logged
    calls = [c.args[0] for c in deps.audit.log.call_args_list]
    assert "tool.call" in calls
    assert "tool.result" in calls
