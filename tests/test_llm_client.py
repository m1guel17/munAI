"""Tests for llm_client: client construction, env-var override, generate, astream."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from munai import llm_client


# ── Helpers ────────────────────────────────────────────────────────────────────

def _provider(
    base_url: str = "https://api.openai.com/v1",
    api_key_env: str | None = "TEST_API_KEY",
    api_format: str = "openai",
    timeout_seconds: int = 60,
    extra_headers: dict | None = None,
):
    from munai.config import ApiFormat, ProviderConfig

    return ProviderConfig(
        name="test",
        base_url=base_url,
        api_format=ApiFormat.OPENAI if api_format == "openai" else ApiFormat.ANTHROPIC,
        api_key_env=api_key_env,
        model="test-model",
        extra_headers=extra_headers or {},
        timeout_seconds=timeout_seconds,
    )


def _anthropic_provider():
    return _provider(
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        api_format="anthropic",
    )


def _make_chunk(content: str | None = None, finish_reason: str | None = None, tool_calls=None):
    """Build a minimal streaming chunk object."""
    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _make_tool_call_chunk(index: int, name: str | None, args: str, tc_id: str | None = None,
                          finish_reason: str | None = None):
    tc = SimpleNamespace(
        index=index,
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=args),
    )
    delta = SimpleNamespace(content=None, tool_calls=[tc])
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


async def _aiter(items):
    for item in items:
        yield item


# ── build_client ───────────────────────────────────────────────────────────────

def test_build_client_openai_compat(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    import openai
    provider = _provider()
    client = llm_client.build_client(provider)
    assert isinstance(client, openai.AsyncOpenAI)
    assert str(client.base_url).rstrip("/") == "https://api.openai.com/v1"


def test_build_client_anthropic_adds_version_header(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    provider = _anthropic_provider()
    client = llm_client.build_client(provider)
    # anthropic-version header should be present in default_headers
    assert "anthropic-version" in client.default_headers


def test_build_client_no_key_uses_sentinel(monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    provider = _provider(api_key_env=None)
    import openai
    client = llm_client.build_client(provider)
    assert isinstance(client, openai.AsyncOpenAI)


# ── get_env_override ──────────────────────────────────────────────────────────

def test_get_env_override_full(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-ds-123")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    result = llm_client.get_env_override()
    assert result is not None
    base_url, api_key, model = result
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-ds-123"
    assert model == "deepseek-chat"


def test_get_env_override_partial_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert llm_client.get_env_override() is None


def test_get_env_override_not_set_returns_none(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert llm_client.get_env_override() is None


def test_get_env_override_dollar_ref(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "$MY_SECRET_KEY")
    monkeypatch.setenv("MY_SECRET_KEY", "resolved-key")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    result = llm_client.get_env_override()
    assert result is not None
    _, api_key, _ = result
    assert api_key == "resolved-key"


def test_get_env_override_dollar_ref_missing_resolves_to_sentinel(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "$MISSING_VAR_XYZ")
    monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
    monkeypatch.setenv("LLM_MODEL", "my-model")
    result = llm_client.get_env_override()
    assert result is not None
    _, api_key, _ = result
    assert api_key == llm_client._NO_KEY


# ── generate ──────────────────────────────────────────────────────────────────

async def test_generate_returns_text():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello, world!"
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await llm_client.generate(
        mock_client, "test-model",
        [{"role": "user", "content": "Hi"}],
    )
    assert result == "Hello, world!"


async def test_generate_prepends_system():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "OK"
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    await llm_client.generate(
        mock_client, "test-model",
        [{"role": "user", "content": "Hi"}],
        system="You are a helpful assistant.",
    )
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "helpful" in messages[0]["content"]


async def test_generate_timeout_raises():
    mock_client = MagicMock()

    async def slow_create(**kwargs):
        await asyncio.sleep(999)

    mock_client.chat.completions.create = slow_create

    with pytest.raises(asyncio.TimeoutError):
        await llm_client.generate(
            mock_client, "test-model",
            [{"role": "user", "content": "Hi"}],
            timeout=0.01,
        )


# ── astream ───────────────────────────────────────────────────────────────────

async def test_astream_yields_text_deltas():
    mock_client = MagicMock()
    chunks = [
        _make_chunk("Hello"),
        _make_chunk(", "),
        _make_chunk("world!"),
        _make_chunk(finish_reason="stop"),
    ]
    mock_client.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

    collected = []
    async for item in llm_client.astream(mock_client, "model", [{"role": "user", "content": "hi"}]):
        collected.append(item)

    assert collected == ["Hello", ", ", "world!"]


async def test_astream_yields_tool_calls_list():
    mock_client = MagicMock()
    chunks = [
        _make_tool_call_chunk(0, "file_read", "", "tc-1"),
        _make_tool_call_chunk(0, None, '{"path": "foo.txt"}'),
        _make_tool_call_chunk(0, None, "", finish_reason="tool_calls"),
    ]
    mock_client.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

    collected = []
    async for item in llm_client.astream(mock_client, "model", [{"role": "user", "content": "read"}]):
        collected.append(item)

    # Last item should be the tool_calls list
    assert isinstance(collected[-1], list)
    tc_list = collected[-1]
    assert tc_list[0]["function"]["name"] == "file_read"
    assert tc_list[0]["function"]["arguments"] == '{"path": "foo.txt"}'


async def test_astream_accumulates_split_arguments():
    """Tool args arriving in separate chunks should be joined."""
    mock_client = MagicMock()
    chunks = [
        _make_tool_call_chunk(0, "shell_exec", "", "tc-2"),
        _make_tool_call_chunk(0, None, '{"command":'),
        _make_tool_call_chunk(0, None, ' ["ls"]}'),
        _make_tool_call_chunk(0, None, "", finish_reason="tool_calls"),
    ]
    mock_client.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

    tool_calls = None
    async for item in llm_client.astream(mock_client, "model", [{"role": "user", "content": "ls"}]):
        if isinstance(item, list):
            tool_calls = item

    assert tool_calls is not None
    assert tool_calls[0]["function"]["arguments"] == '{"command": ["ls"]}'


async def test_astream_no_tool_calls_no_list_yielded():
    mock_client = MagicMock()
    chunks = [_make_chunk("Simple response", finish_reason="stop")]
    mock_client.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

    items = []
    async for item in llm_client.astream(mock_client, "model", []):
        items.append(item)

    # Should only have string items, no list
    assert all(isinstance(i, str) for i in items)
