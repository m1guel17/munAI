"""Agent Runtime: the core agentic loop with tool dispatch and streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from ..audit.logger import AuditLogger
from ..config import Config
from .compaction import Compactor, apply_compaction
from .context import ContextAssembler
from .model_resolver import ModelResolver
from .session import SessionManager

log = logging.getLogger(__name__)

# Type alias for the emit callback: (event_name, payload) -> None
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]
# Type for the approval callback: (approval_id, command, session_id) -> bool
ApprovalFn = Callable[[str, list[str], str], Awaitable[bool]]

# Maximum tool-call rounds per agent turn (prevents runaway loops)
_MAX_TOOL_ROUNDS = 10


class AgentRuntime:
    """Orchestrates a single agent turn: context -> LLM -> tool dispatch -> persist.

    The emit callback decouples the runtime from the transport layer.
    The request_approval callback enables shell command approval via the Gateway.
    """

    def __init__(
        self,
        config: Config,
        session_manager: SessionManager,
        audit: AuditLogger,
        request_approval: ApprovalFn | None = None,
    ) -> None:
        self._config = config
        self._session_manager = session_manager
        self._audit = audit
        self._context = ContextAssembler(config.agent)
        self._resolver = ModelResolver(config.models)
        self._compactor = Compactor(self._resolver)
        # Default approval callback: always deny (safe default when no gateway is wired)
        self._request_approval: ApprovalFn = request_approval or _deny_all

    @property
    def context(self) -> ContextAssembler:
        return self._context

    async def run_turn(
        self,
        session_id: str,
        channel: str,
        sender_id: str,
        text: str,
        emit: EmitFn,
        abort_event: asyncio.Event | None = None,
    ) -> str:
        """Execute one full agent turn and return the final text response."""
        start_time = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()

        await self._audit.log(
            "agent.turn_start",
            detail={"trigger": "message", "channel": channel},
            session_id=session_id,
            channel=channel,
        )

        # Step 1: Load history
        history = await self._session_manager.load(session_id)

        # Step 2: Persist user message BEFORE LLM call
        user_event: dict[str, Any] = {
            "type": "user",
            "timestamp": timestamp,
            "channel": channel,
            "sender": sender_id,
            "text": text,
            "attachments": [],
        }
        await self._session_manager.append(session_id, user_event)
        history.append(user_event)

        # Step 3: Compact if needed, then assemble context.
        history_for_context = history[:-1]
        if self._context.needs_compaction(history_for_context):
            history_for_context = await self._compact_session(
                session_id, history_for_context, channel
            )

        system_prompt, messages = self._context.assemble(history_for_context)

        # Step 4: Run the agentic loop
        response_text = await self._run_agent(
            system_prompt=system_prompt,
            messages=messages,
            user_text=text,
            session_id=session_id,
            channel=channel,
            emit=emit,
            abort_event=abort_event,
        )

        # Step 6: Persist assistant response
        duration_ms = int((time.monotonic() - start_time) * 1000)
        _primary = self._config.models.providers[self._config.models.primary]
        assistant_event: dict[str, Any] = {
            "type": "assistant",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text": response_text,
            "model": _primary.model,
        }
        await self._session_manager.append(session_id, assistant_event)

        # Step 7: Audit turn end
        await self._audit.log(
            "agent.turn_end",
            detail={"duration_ms": duration_ms, "model": _primary.model},
            session_id=session_id,
            channel=channel,
        )

        return response_text

    async def _compact_session(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        channel: str,
    ) -> list[dict[str, Any]]:
        """Run compaction on the session history and persist the compaction event."""
        log.info("Compacting session %s", session_id)
        summary, turns_compacted = await self._compactor.compact(history)

        if turns_compacted == 0:
            return history

        new_history, compaction_event = apply_compaction(
            history, summary, turns_compacted, session_id
        )

        await self._session_manager.append(session_id, compaction_event)
        await self._audit.log(
            "agent.compaction",
            detail={"turns_compacted": turns_compacted},
            session_id=session_id,
            channel=channel,
        )
        return new_history

    async def _run_agent(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        user_text: str,
        session_id: str,
        channel: str,
        emit: EmitFn,
        abort_event: asyncio.Event | None = None,
    ) -> str:
        """Run the agentic loop with tool dispatch and streaming."""
        from .. import llm_client

        start_time = time.monotonic()

        _primary = self._config.models.providers[self._config.models.primary]
        await self._audit.log(
            "agent.model_call",
            detail={
                "provider": self._config.models.primary,
                "model": _primary.model,
            },
            session_id=session_id,
            channel=channel,
        )

        tool_deps = self._make_tool_deps(session_id, channel, emit)
        tool_defs = _get_tool_definitions(self._config)

        # Messages from ContextAssembler.assemble() are already in OpenAI {role, content} format
        llm_messages = list(messages) + [{"role": "user", "content": user_text}]

        # Failover loop: try primary (index 0), then fallback[0], fallback[1], ...
        model_index = 0
        full_text = ""
        while True:
            try:
                client, model, provider = self._resolver.get_client(model_index)
            except RuntimeError:
                error_msg = "All configured models failed or are unavailable."
                log.error(error_msg)
                await emit("agent.done", {"text": error_msg, "error": True})
                return error_msg

            try:
                full_text = await self._run_agentic_loop(
                    client=client,
                    model=model,
                    provider=provider,
                    messages=llm_messages,
                    system=system_prompt,
                    tool_defs=tool_defs,
                    tool_deps=tool_deps,
                    emit=emit,
                    abort_event=abort_event,
                )
                break  # success — exit the failover loop

            except Exception as exc:
                if model_index < self._resolver.model_count() - 1:
                    log.warning(
                        "Model index %d failed (%s), trying next fallback",
                        model_index, exc,
                    )
                    model_index += 1
                    continue
                log.exception("All models failed")
                error_msg = f"LLM error (all models failed): {exc}"
                await emit("agent.done", {"text": error_msg, "error": True})
                return error_msg

        duration_ms = int((time.monotonic() - start_time) * 1000)
        await self._audit.log(
            "agent.model_call_complete",
            detail={"duration_ms": duration_ms},
            session_id=session_id,
            channel=channel,
        )

        # Rough token estimate: ~4 chars per token (ASCII average)
        chars_in = sum(len(str(m.get("content") or "")) for m in llm_messages)
        tokens_in = max(1, chars_in // 4)
        tokens_out = max(1, len(full_text) // 4)
        await emit("agent.done", {
            "text": full_text,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })
        return full_text

    async def _run_agentic_loop(
        self,
        *,
        client: Any,
        model: str,
        provider: Any,
        messages: list[dict[str, Any]],
        system: str,
        tool_defs: list[dict],
        tool_deps: Any,
        emit: EmitFn,
        abort_event: asyncio.Event | None = None,
    ) -> str:
        """Inner agentic loop: stream -> tool dispatch -> stream (up to _MAX_TOOL_ROUNDS)."""
        from .. import llm_client

        local_msgs = list(messages)
        full_text = ""

        for _round in range(_MAX_TOOL_ROUNDS):
            tool_calls_received: list[dict] | None = None
            aborted = False

            async for item in llm_client.astream(
                client,
                model,
                local_msgs,
                system=system,
                tools=tool_defs or None,
                timeout=float(provider.timeout_seconds),
            ):
                if isinstance(item, list):
                    tool_calls_received = item
                else:
                    full_text += item
                    await emit("agent.delta", {"text": item})
                if abort_event and abort_event.is_set():
                    aborted = True
                    break

            if aborted:
                full_text += " [aborted]"
                break

            if not tool_calls_received:
                break  # no tool calls — we have the final answer

            # Append the assistant's tool-call turn to local history
            local_msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_received,
            })

            # Execute each tool and collect results
            for tc in tool_calls_received:
                result = await _dispatch_tool(tc, tool_deps, self._config)
                local_msgs.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tc["id"],
                })

            full_text = ""  # reset; the next LLM response is the final answer

        return full_text

    def _make_tool_deps(
        self,
        session_id: str,
        channel: str,
        emit: EmitFn,
    ) -> Any:
        """Build the ToolDeps object for a single turn."""
        from ..tools.base import ToolDeps
        from ..tools.policy import ToolPolicyEnforcer
        from ..tools.sandbox import PathSandbox

        workspace = self._config.agent.workspace_path
        sandbox = PathSandbox(workspace)
        policy = ToolPolicyEnforcer(self._config.tools)

        async def request_approval(
            approval_id: str,
            command: list[str],
            sid: str,
        ) -> bool:
            return await self._request_approval(approval_id, command, sid)

        return ToolDeps(
            workspace_path=workspace,
            sandbox=sandbox,
            policy=policy,
            audit=self._audit,
            session_id=session_id,
            channel=channel,
            emit=emit,
            request_approval=request_approval,
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _get_tool_definitions(config: Config) -> list[dict]:
    """Return OpenAI tool definition dicts for tools enabled by the current config."""
    from ..tools.file_read import SCHEMA as FR_SCHEMA
    from ..tools.file_write import SCHEMA as FW_SCHEMA
    from ..tools.file_edit import SCHEMA as FE_SCHEMA
    from ..tools.shell_exec import SCHEMA as SE_SCHEMA

    schema_map = {
        "file_read": FR_SCHEMA,
        "file_write": FW_SCHEMA,
        "file_edit": FE_SCHEMA,
        "shell_exec": SE_SCHEMA,
    }
    enabled = []
    for name, schema in schema_map.items():
        if name in config.tools.allow and name not in config.tools.deny:
            enabled.append(schema)
    return enabled


async def _dispatch_tool(tc: dict, deps: Any, config: Config) -> str:
    """Execute a single tool call and return its string result."""
    from ..tools.file_read import file_read
    from ..tools.file_write import file_write
    from ..tools.file_edit import file_edit
    from ..tools.shell_exec import shell_exec

    dispatch = {
        "file_read": file_read,
        "file_write": file_write,
        "file_edit": file_edit,
        "shell_exec": shell_exec,
    }

    name = tc.get("function", {}).get("name", "")
    fn = dispatch.get(name)
    if fn is None:
        return f"Unknown tool: {name!r}"

    try:
        args = json.loads(tc["function"].get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON arguments for tool {name!r}: {exc}"

    try:
        return await fn(deps, **args)
    except TypeError as exc:
        return f"Tool argument error ({name}): {exc}"
    except Exception as exc:
        log.exception("Tool %r raised an unexpected exception", name)
        return f"Tool error ({name}): {exc}"


async def _deny_all(approval_id: str, command: list[str], session_id: str) -> bool:
    """Default approval callback: deny all shell commands."""
    log.warning(
        "Shell command denied (no approval handler configured): %s", command
    )
    return False
