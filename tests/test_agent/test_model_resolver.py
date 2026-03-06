"""Tests for ModelResolver: provider resolution, request building, cooldown, failover."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from munai.config import ApiFormat, ModelsConfig, ProviderConfig
from munai.agent.model_resolver import ModelResolver


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _provider(
    name: str = "anthropic",
    model: str = "claude-test",
    api_format: ApiFormat = ApiFormat.ANTHROPIC,
    api_key_env: str | None = "TEST_KEY",
    base_url: str = "https://api.anthropic.com/v1",
    api_key_header: str = "x-api-key",
    api_key_prefix: str = "",
    extra_headers: dict | None = None,
    extra_body: dict | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url=base_url,
        api_format=api_format,
        api_key_env=api_key_env,
        api_key_header=api_key_header,
        api_key_prefix=api_key_prefix,
        model=model,
        extra_headers=extra_headers or {},
        extra_body=extra_body or {},
    )


def _openai_provider(name: str = "openai", model: str = "gpt-4") -> ProviderConfig:
    return _provider(
        name=name,
        model=model,
        api_format=ApiFormat.OPENAI,
        api_key_env="OPENAI_KEY",
        base_url="https://api.openai.com/v1",
        api_key_header="Authorization",
        api_key_prefix="Bearer ",
    )


def _cfg_primary_only(prov: ProviderConfig | None = None) -> ModelsConfig:
    p = prov or _provider()
    return ModelsConfig(primary=p.name, providers={p.name: p})


def _cfg_with_fallback(primary: ProviderConfig, fallback: ProviderConfig) -> ModelsConfig:
    return ModelsConfig(
        primary=primary.name,
        fallback=[fallback.name],
        providers={primary.name: primary, fallback.name: fallback},
    )


# ─── model_count ─────────────────────────────────────────────────────────────

def test_model_count_primary_only():
    resolver = ModelResolver(_cfg_primary_only())
    assert resolver.model_count() == 1


def test_model_count_with_fallbacks():
    p = _provider("primary")
    f1 = _provider("fb1", model="fb1-model")
    f2 = _provider("fb2", model="fb2-model")
    cfg = ModelsConfig(
        primary="primary",
        fallback=["fb1", "fb2"],
        providers={"primary": p, "fb1": f1, "fb2": f2},
    )
    resolver = ModelResolver(cfg)
    assert resolver.model_count() == 3


# ─── resolve_provider ─────────────────────────────────────────────────────────

def test_resolve_provider_primary():
    p = _provider("myprovider")
    resolver = ModelResolver(_cfg_primary_only(p))
    result = resolver.resolve_provider("primary")
    assert result.name == "myprovider"


def test_resolve_provider_heartbeat_when_set():
    primary = _provider("primary")
    hb = _provider("haiku", model="haiku-model")
    cfg = ModelsConfig(
        primary="primary",
        heartbeat="haiku",
        providers={"primary": primary, "haiku": hb},
    )
    resolver = ModelResolver(cfg)
    result = resolver.resolve_provider("heartbeat")
    assert result.name == "haiku"


def test_resolve_provider_heartbeat_falls_back_to_primary():
    p = _provider("primary", model="primary-model")
    resolver = ModelResolver(_cfg_primary_only(p))
    result = resolver.resolve_provider("heartbeat")
    assert result.name == "primary"
    assert result.model == "primary-model"


# ─── build_request — OpenAI format ───────────────────────────────────────────

def test_build_request_openai_url_and_body(monkeypatch):
    monkeypatch.setenv("OPENAI_KEY", "sk-test")
    p = _openai_provider()
    resolver = ModelResolver(_cfg_primary_only(p))
    messages = [{"role": "user", "content": "hi"}]

    url, headers, body = resolver.build_request(p, messages)

    assert url == "https://api.openai.com/v1/chat/completions"
    assert body["model"] == "gpt-4"
    assert body["messages"] == messages
    assert body["stream"] is True


def test_build_request_openai_auth_header(monkeypatch):
    monkeypatch.setenv("OPENAI_KEY", "sk-abc123")
    p = _openai_provider()
    resolver = ModelResolver(_cfg_primary_only(p))

    _, headers, _ = resolver.build_request(p, [])

    assert headers["Authorization"] == "Bearer sk-abc123"


def test_build_request_openai_tools_included_when_supported(monkeypatch):
    monkeypatch.setenv("OPENAI_KEY", "sk-test")
    p = _openai_provider()
    resolver = ModelResolver(_cfg_primary_only(p))
    tools = [{"type": "function", "function": {"name": "foo"}}]

    _, _, body = resolver.build_request(p, [], tools=tools)

    assert body["tools"] == tools


# ─── build_request — Anthropic format ────────────────────────────────────────

def test_build_request_anthropic_url(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-ant-test")
    p = _provider()
    resolver = ModelResolver(_cfg_primary_only(p))

    url, _, _ = resolver.build_request(p, [])

    assert url == "https://api.anthropic.com/v1/messages"


def test_build_request_anthropic_version_header(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-ant-test")
    p = _provider()
    resolver = ModelResolver(_cfg_primary_only(p))

    _, headers, _ = resolver.build_request(p, [])

    assert "anthropic-version" in headers


def test_build_request_anthropic_max_tokens(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-ant-test")
    p = _provider()
    resolver = ModelResolver(_cfg_primary_only(p))

    _, _, body = resolver.build_request(p, [])

    assert "max_tokens" in body
    assert body["max_tokens"] > 0


def test_build_request_anthropic_auth_header(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-ant-secret")
    p = _provider()
    resolver = ModelResolver(_cfg_primary_only(p))

    _, headers, _ = resolver.build_request(p, [])

    assert headers["x-api-key"] == "sk-ant-secret"


# ─── build_request — auth edge cases ─────────────────────────────────────────

def test_build_request_local_provider_no_auth_header():
    """Local providers (api_key_env=None) should not have an auth header."""
    p = _provider(
        name="ollama",
        api_key_env=None,
        api_format=ApiFormat.OPENAI,
        base_url="http://localhost:11434/v1",
        api_key_header="Authorization",
        api_key_prefix="Bearer ",
        model="llama3",
    )
    resolver = ModelResolver(_cfg_primary_only(p))

    _, headers, _ = resolver.build_request(p, [])

    assert "Authorization" not in headers


def test_build_request_missing_api_key_raises():
    """Missing required API key should raise RuntimeError."""
    p = _provider(api_key_env="MISSING_KEY_XYZ_123")
    resolver = ModelResolver(_cfg_primary_only(p))

    with pytest.raises(RuntimeError, match="MISSING_KEY_XYZ_123"):
        resolver.build_request(p, [])


# ─── build_request — extra_headers / extra_body ───────────────────────────────

def test_build_request_extra_headers_applied(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    p = _provider(extra_headers={"X-Custom": "value123"})
    resolver = ModelResolver(_cfg_primary_only(p))

    _, headers, _ = resolver.build_request(p, [])

    assert headers["X-Custom"] == "value123"


def test_build_request_extra_body_merged(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    p = _provider(extra_body={"temperature": 0.7})
    resolver = ModelResolver(_cfg_primary_only(p))

    _, _, body = resolver.build_request(p, [])

    assert body["temperature"] == 0.7


# ─── Cooldown management ─────────────────────────────────────────────────────

def test_set_cooldown_marks_provider_as_cooled_down():
    resolver = ModelResolver(_cfg_primary_only())
    assert not resolver._is_cooled_down("anthropic")

    resolver._set_cooldown("anthropic")

    assert resolver._is_cooled_down("anthropic")


def test_cooldown_expires(monkeypatch):
    """After the cooldown period, the provider should be available again."""
    resolver = ModelResolver(_cfg_primary_only())
    resolver._set_cooldown("anthropic")

    # Simulate time passing beyond the cooldown window
    original_monotonic = time.monotonic
    future = original_monotonic() + 10_000
    monkeypatch.setattr(time, "monotonic", lambda: future)

    assert not resolver._is_cooled_down("anthropic")


def test_cooldown_not_set_returns_false():
    resolver = ModelResolver(_cfg_primary_only())
    assert not resolver._is_cooled_down("unknown-provider")


def test_provider_sequence_excludes_cooled_down():
    primary = _provider("primary")
    fallback = _provider("fallback", model="fb-model")
    cfg = _cfg_with_fallback(primary, fallback)
    resolver = ModelResolver(cfg)

    resolver._set_cooldown("primary")
    sequence = resolver._provider_sequence()

    names = [p.name for p in sequence]
    assert "primary" not in names
    assert "fallback" in names


# --- get_client ---------------------------------------------------------------

def test_get_client_primary(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    primary = _provider("primary", model="primary-model")
    resolver = ModelResolver(_cfg_primary_only(primary))

    with patch("munai.llm_client.build_client", return_value=MagicMock()):
        client, model, provider = resolver.get_client(0)

    assert provider.name == "primary"
    assert model == "primary-model"


def test_get_client_fallback(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    primary = _provider("primary")
    fallback = _provider("fallback", model="fallback-model")
    cfg = _cfg_with_fallback(primary, fallback)
    resolver = ModelResolver(cfg)

    with patch("munai.llm_client.build_client", return_value=MagicMock()):
        client, model, provider = resolver.get_client(1)

    assert provider.name == "fallback"
    assert model == "fallback-model"


def test_get_client_out_of_range_raises():
    resolver = ModelResolver(_cfg_primary_only())
    with pytest.raises(RuntimeError, match="No model at failover index"):
        resolver.get_client(1)


def test_get_client_missing_api_key_raises():
    p = _provider(api_key_env="MISSING_KEY_VAR_XYZ")
    resolver = ModelResolver(_cfg_primary_only(p))
    with pytest.raises(RuntimeError, match="API key"):
        resolver.get_client(0)


# --- get_heartbeat_client -----------------------------------------------------

def test_get_heartbeat_client_when_set():
    primary = _provider("primary")
    hb = _provider("haiku", model="haiku-model")
    cfg = ModelsConfig(
        primary="primary",
        heartbeat="haiku",
        providers={"primary": primary, "haiku": hb},
    )
    resolver = ModelResolver(cfg)
    captured: dict = {}

    def fake_build(provider):
        captured["name"] = provider.name
        return MagicMock()

    with patch("munai.llm_client.build_client", side_effect=fake_build):
        client, model, provider = resolver.get_heartbeat_client()

    assert captured["name"] == "haiku"


def test_get_heartbeat_client_falls_back_to_primary():
    p = _provider("primary", model="primary-model")
    resolver = ModelResolver(_cfg_primary_only(p))
    captured: dict = {}

    def fake_build(provider):
        captured["name"] = provider.name
        return MagicMock()

    with patch("munai.llm_client.build_client", side_effect=fake_build):
        client, model, provider = resolver.get_heartbeat_client()

    assert captured["name"] == "primary"
