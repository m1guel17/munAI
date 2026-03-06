"""shell_exec tool: run a shell command in the workspace with subprocess isolation."""
from __future__ import annotations

import asyncio
import time


from .base import ToolDeps

SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": (
            "Execute a shell command and return its output. "
            "Pass arguments as a list — do NOT use shell=True."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command and arguments as a list, e.g. [\"git\", \"status\"].",
                },
                "cwd": {"type": "string", "description": "Working directory. Defaults to workspace root."},
                "timeout_seconds": {"type": "integer", "description": "Max execution time (capped at 300s). Default 60."},
            },
            "required": ["command"],
        },
    },
}
from .sandbox import make_subprocess_env

# Hard maximum on timeout to prevent runaway processes
MAX_TIMEOUT_SECONDS = 300


async def shell_exec(
    deps: ToolDeps,
    command: list[str],
    cwd: str | None = None,
    timeout_seconds: int = 60,
) -> str:
    """Execute a shell command and return its output.

    Args:
        command: Command and arguments as a list (e.g. ["git", "status"]).
                 Do NOT use shell=True — pass arguments as separate list items.
        cwd: Working directory for the command. Defaults to workspace root.
             Must be within the workspace if workspace_only is enabled.
        timeout_seconds: Maximum execution time. Capped at 300s.

    Returns:
        Combined stdout, stderr, and exit code as a formatted string.
    """
    try:
        deps.policy.check_allowed("shell_exec")
    except Exception as exc:
        return f"Permission denied: {exc}"

    timeout_seconds = min(timeout_seconds, MAX_TIMEOUT_SECONDS)
    request_id = deps.next_request_id()

    # Resolve working directory
    if cwd is not None:
        if deps.policy.workspace_only:
            cwd_path = deps.sandbox.check(cwd)
        else:
            from pathlib import Path
            cwd_path = Path(cwd).resolve()
    else:
        cwd_path = deps.sandbox.root

    # Shell approval gate
    if deps.policy.shell_approval_mode == "always":
        await deps.audit.log(
            "tool.approval_requested",
            detail={"command": command, "cwd": str(cwd_path)},
            session_id=deps.session_id,
            channel=deps.channel,
            request_id=request_id,
        )

        approved = await deps.request_approval(request_id, command, deps.session_id)

        if not approved:
            await deps.audit.log(
                "tool.approval_denied",
                detail={"command": command},
                session_id=deps.session_id,
                channel=deps.channel,
                request_id=request_id,
            )
            await deps.emit("agent.tool_end", {"tool": "shell_exec", "success": False})
            return "Command denied by user."

        await deps.audit.log(
            "tool.approval_granted",
            detail={"command": command},
            session_id=deps.session_id,
            channel=deps.channel,
            request_id=request_id,
        )

    await deps.audit.log(
        "tool.call",
        detail={"tool_name": "shell_exec", "params": {"command": command, "cwd": str(cwd_path)}},
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_start", {
        "tool": "shell_exec",
        "params": {"command": command, "cwd": str(cwd_path)},
    })

    start_time = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd_path),
            env=make_subprocess_env(),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            result = f"Command timed out after {timeout_seconds}s."
            exit_code = -1
            success = False
        else:
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0
            success = exit_code == 0

            parts = []
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            parts.append(f"exit_code: {exit_code}")
            result = "\n".join(parts) if parts else f"exit_code: {exit_code}"
            result = deps.policy.truncate_output(result)

    except FileNotFoundError:
        result = f"Command not found: {command[0]!r}"
        exit_code = 127
        success = False
    except OSError as exc:
        result = f"Failed to start process: {exc}"
        exit_code = -1
        success = False

    duration_ms = int((time.monotonic() - start_time) * 1000)

    await deps.audit.log(
        "tool.result",
        detail={
            "tool_name": "shell_exec",
            "success": success,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "output_length": len(result),
        },
        session_id=deps.session_id,
        channel=deps.channel,
        request_id=request_id,
    )
    await deps.emit("agent.tool_end", {
        "tool": "shell_exec",
        "success": success,
        "exit_code": exit_code,
    })
    return result
