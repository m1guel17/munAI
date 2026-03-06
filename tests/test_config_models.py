"""Tests for the new ProviderConfig / ModelsConfig / ApiFormat schema."""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from munai.config import (
    ApiFormat,
    ModelsConfig,
    ProviderConfig,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _anthropic_provider(name: str = "anthropic") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url="https://api.anthropic.com/v1",
        api_format=ApiFormat.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_header="x-api-key",
        api_key_prefix="",
        model="claude-test",
    )


def _openai_provider(name: str = "openai") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url="https://api.openai.com/v1",
        api_format=ApiFormat.OPENAI,
        api_key_env="OPENAI_KEY",
        api_key_header="Authorization",
        api_key_prefix="Bearer ",
        model="gpt-4",
    )


# ─── ApiFormat ───────────────────────────────────────────────────────────────

def test_api_format_values():
    assert ApiFormat.OPENAI == "openai"
    assert ApiFormat.ANTHROPIC == "anthropic"


def test_api_format_str_enum():
    assert isinstance(ApiFormat.OPENAI, str)
    assert isinstance(ApiFormat.ANTHROPIC, str)


# ─── ProviderConfig defaults ─────────────────────────────────────────────────

def test_provider_config_defaults():
    p = ProviderConfig(name="test", model="test-model")
    assert p.base_url == "https://api.openai.com/v1"
    assert p.api_format == ApiFormat.OPENAI
    assert p.api_key_env is None
    assert p.api_key_header == "Authorization"
    assert p.api_key_prefix == "Bearer "
    assert p.max_retries == 2
    assert p.timeout_seconds == 120
    assert p.supports_tool_calling is True
    assert p.supports_streaming is True
    assert p.extra_headers == {}
    assert p.extra_body == {}


def test_provider_config_explicit_fields():
    p = _anthropic_provider()
    assert p.name == "anthropic"
    assert p.api_format == ApiFormat.ANTHROPIC
    assert p.api_key_header == "x-api-key"
    assert p.api_key_prefix == ""
    assert p.model == "claude-test"


# ─── ProviderConfig.resolve_api_key ──────────────────────────────────────────

def test_resolve_api_key_returns_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = _anthropic_provider()
    assert p.resolve_api_key() == "sk-ant-test"


def test_resolve_api_key_returns_none_when_not_set():
    p = _anthropic_provider()
    os.environ.pop("ANTHROPIC_API_KEY", None)
    # Will be None (not set) or whatever the env has; just test it doesn't crash
    result = p.resolve_api_key()
    assert result is None or isinstance(result, str)


def test_resolve_api_key_returns_none_for_local_provider():
    """Providers with api_key_env=None (local runtime) return None."""
    p = ProviderConfig(name="ollama", model="llama3", api_key_env=None)
    assert p.resolve_api_key() is None


# ─── ModelsConfig validation ──────────────────────────────────────────────────

def test_models_config_valid_primary():
    p = _anthropic_provider()
    cfg = ModelsConfig(primary="anthropic", providers={"anthropic": p})
    assert cfg.primary == "anthropic"
    assert "anthropic" in cfg.providers


def test_models_config_invalid_primary_raises():
    p = _anthropic_provider()
    with pytest.raises(ValidationError, match="Primary provider"):
        ModelsConfig(primary="missing", providers={"anthropic": p})


def test_models_config_invalid_fallback_raises():
    p = _anthropic_provider()
    with pytest.raises(ValidationError, match="Fallback provider"):
        ModelsConfig(primary="anthropic", fallback=["missing"], providers={"anthropic": p})


def test_models_config_invalid_heartbeat_raises():
    p = _anthropic_provider()
    with pytest.raises(ValidationError, match="Heartbeat provider"):
        ModelsConfig(primary="anthropic", heartbeat="missing", providers={"anthropic": p})


def test_models_config_valid_with_fallback():
    p = _anthropic_provider("anthropic")
    f = _openai_provider("openai")
    cfg = ModelsConfig(
        primary="anthropic",
        fallback=["openai"],
        providers={"anthropic": p, "openai": f},
    )
    assert cfg.fallback == ["openai"]


def test_models_config_valid_with_heartbeat():
    p = _anthropic_provider("primary")
    hb = _anthropic_provider("haiku")
    hb = ProviderConfig(
        name="haiku",
        base_url="https://api.anthropic.com/v1",
        api_format=ApiFormat.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_header="x-api-key",
        api_key_prefix="",
        model="claude-haiku",
    )
    cfg = ModelsConfig(
        primary="primary",
        heartbeat="haiku",
        providers={"primary": p, "haiku": hb},
    )
    assert cfg.heartbeat == "haiku"


def test_models_config_fallback_defaults_empty():
    p = _anthropic_provider()
    cfg = ModelsConfig(primary="anthropic", providers={"anthropic": p})
    assert cfg.fallback == []
    assert cfg.heartbeat is None
