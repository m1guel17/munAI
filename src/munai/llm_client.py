"""Thin async wrapper around openai.AsyncOpenAI.

Active provider resolved in priority order:
  1. LLM_BASE_URL + LLM_API_KEY + LLM_MODEL env vars  (fully overrides config)
  2. Caller supplies a ProviderConfig

Never logs API keys.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import openai
    from .config import ProviderConfig

log = logging.getLogger(__name__)

_NO_KEY = "no-key-required"


# ── Client construction ────────────────────────────────────────────────────────

def build_client(provider: "ProviderConfig") -> "openai.AsyncOpenAI":
    """Build an AsyncOpenAI client from a ProviderConfig.

    - All providers (including Anthropic) use the OpenAI-compat endpoint.
    - Anthropic requires an extra header; it is injected via default_headers.
    - Timeout: connect=10s, read=30s (per-chunk, kills stalled streams).
    - max_retries=0: failover is handled at the runtime level.
    """
    import openai
    from .config import ApiFormat

    api_key = provider.resolve_api_key() or _NO_KEY

    default_headers: dict[str, str] = dict(provider.extra_headers)
    if provider.api_format == ApiFormat.ANTHROPIC:
        default_headers.setdefault("anthropic-version", "2023-06-01")

    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=provider.base_url,
        timeout=openai.Timeout(timeout=30.0, connect=10.0),
        default_headers=default_headers or None,
        max_retries=0,
    )


def get_env_override() -> "tuple[str, str, str] | None":
    """Return (base_url, api_key, model) from LLM_* env vars, or None if not fully set.

    LLM_API_KEY may be a literal key value or a ``$VAR_NAME`` reference that is
    resolved against the environment (useful for referencing provider-specific vars).
    """
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key_raw = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    if not (base_url and model):
        return None

    if api_key_raw.startswith("$"):
        api_key = os.environ.get(api_key_raw[1:], "") or _NO_KEY
    else:
        api_key = api_key_raw or _NO_KEY

    return base_url, api_key, model


def build_client_from_env() -> "tuple[openai.AsyncOpenAI, str]":
    """Build (client, model) purely from LLM_* env vars. Raises RuntimeError if not set."""
    import openai

    override = get_env_override()
    if override is None:
        raise RuntimeError(
            "LLM_BASE_URL and LLM_MODEL env vars must be set to use env-var-only mode."
        )
    base_url, api_key, model = override
    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=openai.Timeout(timeout=30.0, connect=10.0),
        max_retries=0,
    )
    return client, model


# ── LLM call helpers ───────────────────────────────────────────────────────────

async def generate(
    client: "openai.AsyncOpenAI",
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    timeout: float = 60.0,
) -> str:
    """Non-streaming LLM call. Returns the full response text.

    Args:
        client: AsyncOpenAI instance.
        model: Model identifier string.
        messages: List of {role, content} dicts (system message NOT included here).
        system: System prompt; prepended as a system message if provided.
        tools: OpenAI tool definition list.
        timeout: Total timeout in seconds (wraps the entire call).

    Returns:
        The assistant's text reply.

    Raises:
        asyncio.TimeoutError: if the call takes longer than ``timeout`` seconds.
    """
    full_messages = _prepend_system(messages, system)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await asyncio.wait_for(
        client.chat.completions.create(**kwargs),
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


async def astream(
    client: "openai.AsyncOpenAI",
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[str | list[dict]]:
    """Streaming LLM call with tool-call support.

    Yields:
        str         — text delta chunks as they arrive.
        list[dict]  — complete tool_calls list when finish_reason is "tool_calls".
                      The caller should execute the tools, append results, and
                      re-call astream with the updated message list.

    Tool-call argument deltas are accumulated internally and yielded as a single
    complete list at the end of the stream — callers never see partial JSON.

    Raises:
        asyncio.TimeoutError: if the initial connection takes > 10s or any chunk
                              takes > 30s (configured via openai.Timeout on client).
    """
    full_messages = _prepend_system(messages, system)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "stream": True,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    stream = await client.chat.completions.create(**kwargs)

    tool_calls_acc: dict[int, dict] = {}
    finish_reason: str | None = None

    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]

        # Accumulate tool-call argument fragments
        for tc in choice.delta.tool_calls or []:
            idx = tc.index
            if idx not in tool_calls_acc:
                tool_calls_acc[idx] = {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {"name": tc.function.name or "", "arguments": ""},
                }
            else:
                if tc.id:
                    tool_calls_acc[idx]["id"] = tc.id
                if tc.function.name:
                    tool_calls_acc[idx]["function"]["name"] = tc.function.name
            if tc.function.arguments:
                tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

        # Yield text deltas
        if choice.delta.content:
            yield choice.delta.content

        if choice.finish_reason:
            finish_reason = choice.finish_reason

    # Yield completed tool_calls list if the model requested tool use
    if finish_reason == "tool_calls" and tool_calls_acc:
        yield list(tool_calls_acc.values())


# ── Internal helpers ───────────────────────────────────────────────────────────

def _prepend_system(
    messages: list[dict[str, Any]], system: str | None
) -> list[dict[str, Any]]:
    if system:
        return [{"role": "system", "content": system}] + messages
    return messages
