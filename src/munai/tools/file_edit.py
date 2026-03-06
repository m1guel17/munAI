"""file_edit tool: find-and-replace within a workspace file."""
from __future__ import annotations

from pathlib import Path


from .base import ToolDeps

SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "file_edit",
        "description": "Replace a unique string in a file. old_text must appear exactly once.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to workspace or absolute within workspace)."},
                "old_text": {"type": "string", "description": "The exact text to find. Must match exactly once in the file."},
                "new_text": {"type": "string", "description": "The text to replace it with."},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
}


async def file_edit(
    deps: ToolDeps,
    path: str,
    old_text: str,
    new_text: str,
) -> str:
    """Replace a unique string in a file.

    Args:
        path: Path to the file (relative to workspace, or absolute within workspace).
        old_text: The exact text to find. Must match exactly once in the file.
        new_text: The text to replace it with.

    Returns:
        A success message or error if old_text is not found or is not unique.
    """
    deps.policy.check_allowed("file_edit")

    request_id = deps.next_request_id()
    resolved = deps.sandbox.check(path) if deps.policy.workspace_only else Path(path).resolve()

    await deps.audit.log(
        "tool.call",
        detail={
            "tool_name": "file_edit",
            "params": {
                "path": path,
                "old_text_length": len(old_text),
                "new_text_length": len(new_text),
            },
        },
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_start", {"tool": "file_edit", "params": {"path": path}})

    try:
        if not resolved.exists():
            result = f"Error: file not found: {path}"
            success = False
        else:
            content = resolved.read_text(encoding="utf-8")
            count = content.count(old_text)
            if count == 0:
                result = f"Error: old_text not found in {path}. No changes made."
                success = False
            elif count > 1:
                result = (
                    f"Error: old_text appears {count} times in {path}. "
                    "Provide more context to make it unique. No changes made."
                )
                success = False
            else:
                new_content = content.replace(old_text, new_text, 1)
                resolved.write_text(new_content, encoding="utf-8")
                result = f"Edit applied to {path}."
                success = True
    except PermissionError as exc:
        result = f"Permission denied: {exc}"
        success = False
    except OSError as exc:
        result = f"Error editing file: {exc}"
        success = False

    await deps.audit.log(
        "tool.result",
        detail={"tool_name": "file_edit", "success": success, "output_length": len(result)},
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_end", {"tool": "file_edit", "success": success})
    return result
