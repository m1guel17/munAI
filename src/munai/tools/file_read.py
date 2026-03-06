"""file_read tool: read a file from the workspace."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path


from .base import ToolDeps

SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": (
            "Read a file and return its contents. "
            "Text files are returned as-is; binary files are returned as base64."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to workspace or absolute within workspace)."},
                "line_start": {"type": "integer", "description": "First line to read (1-indexed, inclusive). Optional."},
                "line_end": {"type": "integer", "description": "Last line to read (1-indexed, inclusive). Optional."},
            },
            "required": ["path"],
        },
    },
}


async def file_read(
    deps: ToolDeps,
    path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Read a file and return its contents.

    Args:
        path: Path to the file (relative to workspace, or absolute within workspace).
        line_start: First line to read (1-indexed, inclusive). Optional.
        line_end: Last line to read (1-indexed, inclusive). Optional.

    Returns:
        File contents as a string. Binary files are returned as base64.
    """
    deps.policy.check_allowed("file_read")

    request_id = deps.next_request_id()
    try:
        resolved = deps.sandbox.check(path) if deps.policy.workspace_only else Path(path).resolve()
    except PermissionError as exc:
        return f"Permission denied: {exc}"

    await deps.audit.log(
        "tool.call",
        detail={
            "tool_name": "file_read",
            "params": {"path": path, "line_start": line_start, "line_end": line_end},
        },
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_start", {"tool": "file_read", "params": {"path": path}})

    try:
        if not resolved.exists():
            result = f"Error: file not found: {path}"
            success = False
        else:
            # Check if binary
            mime, _ = mimetypes.guess_type(str(resolved))
            is_text = mime is None or mime.startswith("text/") or mime in {
                "application/json", "application/xml", "application/javascript",
                "application/x-yaml",
            }

            if is_text:
                text = resolved.read_text(encoding="utf-8", errors="replace")
                if line_start is not None or line_end is not None:
                    lines = text.splitlines(keepends=True)
                    start = max(0, (line_start or 1) - 1)
                    end = line_end if line_end is not None else len(lines)
                    text = "".join(lines[start:end])
                result = deps.policy.truncate_output(text)
            else:
                data = resolved.read_bytes()
                result = f"[binary file, base64]\n{base64.b64encode(data).decode()}"
                result = deps.policy.truncate_output(result)
            success = True
    except PermissionError as exc:
        result = f"Permission denied: {exc}"
        success = False
    except OSError as exc:
        result = f"Error reading file: {exc}"
        success = False

    await deps.audit.log(
        "tool.result",
        detail={
            "tool_name": "file_read",
            "success": success,
            "output_length": len(result),
        },
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_end", {"tool": "file_read", "success": success})
    return result
