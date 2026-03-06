"""Tests for PathSandbox path containment enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from munai.tools.sandbox import PathSandbox, make_subprocess_env


@pytest.fixture
def sandbox(tmp_path: Path) -> PathSandbox:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return PathSandbox(workspace)


def test_relative_path_inside(sandbox: PathSandbox, tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "notes.md").write_text("hi")
    result = sandbox.check("notes.md")
    assert result == (workspace / "notes.md").resolve()


def test_absolute_path_inside(sandbox: PathSandbox, tmp_path: Path):
    workspace = tmp_path / "workspace"
    target = workspace / "sub" / "file.txt"
    result = sandbox.check(str(target))
    assert result == target.resolve()


def test_path_traversal_blocked(sandbox: PathSandbox):
    with pytest.raises(PermissionError, match="outside"):
        sandbox.check("../../etc/passwd")


def test_absolute_path_outside_blocked(sandbox: PathSandbox):
    with pytest.raises(PermissionError, match="outside"):
        sandbox.check("/etc/passwd")


def test_is_inside_true(sandbox: PathSandbox):
    assert sandbox.is_inside("notes.md") is True


def test_is_inside_false(sandbox: PathSandbox):
    assert sandbox.is_inside("../../secret") is False


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin privileges on Windows")
def test_symlink_traversal_blocked(sandbox: PathSandbox, tmp_path: Path):
    """A symlink inside the workspace pointing outside must be blocked."""
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = workspace / "escape.txt"
    link.symlink_to(outside)
    with pytest.raises(PermissionError, match="outside"):
        sandbox.check("escape.txt")


def test_make_subprocess_env_no_secrets():
    """Subprocess env must not contain API keys from parent process."""
    import os
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-secret"
    env = make_subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_make_subprocess_env_has_path():
    env = make_subprocess_env()
    assert "PATH" in env


def test_make_subprocess_env_extra():
    env = make_subprocess_env(extra_env={"MY_VAR": "hello"})
    assert env["MY_VAR"] == "hello"
