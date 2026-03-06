"""file_write tool: create or overwrite a file in the workspace."""
from __future__ import annotations

from pathlib import Path


from .base import ToolDeps

SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "file_write",
        "description": "Create or completely overwrite a file with new content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to workspace or absolute within workspace)."},
                "content": {"type": "string", "description": "The full content to write."},
            },
            "required": ["path", "content"],
        },
    },
}


async def file_write(
    deps: ToolDeps,
    path: str,
    content: str,
) -> str:
    """Create or completely overwrite a file with new content.

    Args:
        path: Path to the file (relative to workspace, or absolute within workspace).
        content: The full content to write.

    Returns:
        A success or error message.
    """
    deps.policy.check_allowed("file_write")

    request_id = deps.next_request_id()
    try:
        resolved = deps.sandbox.check(path) if deps.policy.workspace_only else Path(path).resolve()
    except PermissionError as exc:
        return f"Permission denied: {exc}"

    await deps.audit.log(
        "tool.call",
        detail={
            "tool_name": "file_write",
            "params": {"path": path, "content_length": len(content)},
        },
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_start", {"tool": "file_write", "params": {"path": path}})

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        result = f"File written: {path} ({len(content)} chars)"
        success = True
    except PermissionError as exc:
        result = f"Permission denied: {exc}"
        success = False
    except OSError as exc:
        result = f"Error writing file: {exc}"
        success = False

    await deps.audit.log(
        "tool.result",
        detail={"tool_name": "file_write", "success": success, "output_length": len(result)},
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_end", {"tool": "file_write", "success": success})
    return result
