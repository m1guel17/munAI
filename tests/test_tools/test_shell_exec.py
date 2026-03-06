"""Tests for shell_exec tool."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from munai.config import ToolsConfig
from munai.tools.base import ToolDeps
from munai.tools.policy import ToolPolicyEnforcer
from munai.tools.sandbox import PathSandbox


# ─── Fixtures ────────────────────────────────────────────────────────────────



def make_deps(workspace: Path, allow: list[str] | None = None, approval_mode: str = "never") -> ToolDeps:
    tools_cfg = ToolsConfig(
        allow=allow or ["shell_exec"],
        deny=[],
        shell_approval_mode=approval_mode,
    )
    sandbox = PathSandbox(workspace)
    policy = ToolPolicyEnforcer(tools_cfg)
    audit = AsyncMock()
    audit.log = AsyncMock()
    emit = AsyncMock()
    request_approval = AsyncMock(return_value=True)
    return ToolDeps(
        workspace_path=workspace,
        sandbox=sandbox,
        policy=policy,
        audit=audit,
        session_id="test-session",
        channel="test",
        emit=emit,
        request_approval=request_approval,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ─── Basic execution ─────────────────────────────────────────────────────────

async def test_shell_exec_simple_command(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    # Use a cross-platform command
    cmd = [sys.executable, "-c", "print('hello')"]
    deps = make_deps(workspace)
    result = await shell_exec(deps, cmd)
    assert "hello" in result
    assert "exit_code: 0" in result


async def test_shell_exec_exit_nonzero(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
    deps = make_deps(workspace)
    result = await shell_exec(deps, cmd)
    assert "42" in result


async def test_shell_exec_stderr_captured(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('err msg\n')"]
    deps = make_deps(workspace)
    result = await shell_exec(deps, cmd)
    assert "err msg" in result


async def test_shell_exec_command_not_found(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace)
    result = await shell_exec(deps, ["__nonexistent_binary_xyz__"])
    assert "not found" in result.lower() or "Failed" in result


async def test_shell_exec_timeout(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    deps = make_deps(workspace)
    result = await shell_exec(deps, cmd, timeout_seconds=1)
    assert "timed out" in result.lower()


# ─── Approval gate ───────────────────────────────────────────────────────────

async def test_shell_exec_approval_required_and_granted(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace, approval_mode="always")
    deps.request_approval = AsyncMock(return_value=True)
    result = await shell_exec(deps, [sys.executable, "-c", "print('ok')"])
    # Approval was granted → command ran
    assert "ok" in result
    deps.request_approval.assert_called_once()


async def test_shell_exec_approval_denied(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace, approval_mode="always")
    deps.request_approval = AsyncMock(return_value=False)
    result = await shell_exec(deps, [sys.executable, "-c", "print('should not run')"])
    assert "denied" in result.lower()
    deps.request_approval.assert_called_once()


async def test_shell_exec_no_approval_when_mode_never(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace, approval_mode="never")
    deps.request_approval = AsyncMock(return_value=True)
    await shell_exec(deps, [sys.executable, "-c", "print('ok')"])
    # request_approval should NOT be called when mode is "never"
    deps.request_approval.assert_not_called()


# ─── Policy enforcement ──────────────────────────────────────────────────────

async def test_shell_exec_denied_by_policy(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    # shell_exec not in allow list
    deps = make_deps(workspace, allow=["file_read"])
    result = await shell_exec(deps, [sys.executable, "-c", "print('x')"])
    assert "not allowed" in result.lower() or "denied" in result.lower() or "Permission" in result


# ─── Audit logging ───────────────────────────────────────────────────────────

async def test_shell_exec_logs_tool_call_and_result(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace)
    await shell_exec(deps, [sys.executable, "-c", "print('x')"])
    calls = [c.args[0] for c in deps.audit.log.call_args_list]
    assert "tool.call" in calls
    assert "tool.result" in calls


async def test_shell_exec_emits_tool_start_and_end(workspace: Path):
    from munai.tools.shell_exec import shell_exec

    deps = make_deps(workspace)
    await shell_exec(deps, [sys.executable, "-c", "print('x')"])
    emitted = [c.args[0] for c in deps.emit.call_args_list]
    assert "agent.tool_start" in emitted
    assert "agent.tool_end" in emitted


# ─── Timeout capping ─────────────────────────────────────────────────────────

async def test_shell_exec_timeout_capped_at_max(workspace: Path):
    """Timeout > 300 should be silently capped."""
    from munai.tools.shell_exec import shell_exec, MAX_TIMEOUT_SECONDS

    # We can't easily test 300s, but we can verify the cap doesn't error out
    deps = make_deps(workspace)
    # Just verify oversized timeout doesn't raise
    result = await shell_exec(deps, [sys.executable, "-c", "print('x')"], timeout_seconds=99999)
    assert "x" in result
