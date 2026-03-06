"""Path containment and environment isolation for tool execution."""
from __future__ import annotations

import os
from pathlib import Path


class PathSandbox:
    """Enforces that file operations stay within the workspace directory.

    Uses resolved absolute paths (symlinks expanded) to prevent traversal attacks.
    """

    def __init__(self, workspace_root: Path) -> None:
        # Resolve once at construction time
        self._root = workspace_root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def check(self, path: str | Path) -> Path:
        """Resolve *path* and verify it is inside the workspace root.

        Returns the resolved absolute Path on success.

        Raises:
            PermissionError: if the resolved path escapes the workspace.
        """
        target = Path(path)
        # If relative, anchor to workspace root
        if not target.is_absolute():
            target = self._root / target
        resolved = target.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise PermissionError(
                f"Path '{path}' resolves to '{resolved}' which is outside "
                f"the workspace root '{self._root}'. "
                "Set workspace_only=false in config to allow access outside the workspace."
            )
        return resolved

    def is_inside(self, path: str | Path) -> bool:
        """Return True if *path* is safely inside the workspace root."""
        try:
            self.check(path)
            return True
        except PermissionError:
            return False


# Minimal set of environment variables to pass through to subprocesses.
# Never inherit the full environment — it may contain secrets.
_SAFE_ENV_VARS = {
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "COLORTERM",
    "SHELL",
}


def make_subprocess_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal, safe environment for subprocess execution.

    Only passes through a whitelist of environment variables.
    Never inherits API keys, tokens, or other secrets from the parent process.
    """
    env: dict[str, str] = {}
    for key in _SAFE_ENV_VARS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    if extra_env:
        env.update(extra_env)
    return env
