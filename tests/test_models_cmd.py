"""Tests for munai models CLI commands (list, add, remove, set-primary, test)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from munai.config import ApiFormat, ModelsConfig, ProviderConfig


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_config(providers: dict | None = None) -> dict:
    """Return a minimal raw config dict with one provider."""
    if providers is None:
        providers = {
            "anthropic": {
                "name": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "api_format": "anthropic",
                "api_key_env": "ANTHROPIC_API_KEY",
                "api_key_header": "x-api-key",
                "api_key_prefix": "",
                "model": "claude-sonnet-4-5-20250929",
                "supports_tool_calling": True,
                "timeout_seconds": 120,
            }
        }
    return {"models": {"primary": list(providers)[0], "fallback": [], "heartbeat": None, "providers": providers}}


def _make_pydantic_config(raw: dict):
    """Build a full Config object from a raw dict."""
    from munai.config import Config
    return Config.model_validate(raw)


# ─── munai models list ────────────────────────────────────────────────────────

def test_list_command_prints_providers(capsys, monkeypatch):
    """_cmd_list prints all configured providers."""
    from munai.cli.models_cmd import _cmd_list

    raw = _make_config()
    cfg = _make_pydantic_config(raw)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with patch("munai.cli.models_cmd._load_dotenv"):
        with patch("munai.config.load_config_or_defaults", return_value=cfg):
            _cmd_list()

    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "claude-sonnet" in out


def test_list_command_marks_missing_key(capsys, monkeypatch):
    """_cmd_list shows missing key indicator when env var is not set."""
    from munai.cli.models_cmd import _cmd_list

    raw = _make_config()
    cfg = _make_pydantic_config(raw)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("munai.config.load_config_or_defaults", return_value=cfg):
        _cmd_list()

    out = capsys.readouterr().out
    assert "missing" in out


def test_list_command_shows_primary(capsys, monkeypatch):
    """_cmd_list prints the primary provider label."""
    from munai.cli.models_cmd import _cmd_list

    raw = _make_config()
    cfg = _make_pydantic_config(raw)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("munai.config.load_config_or_defaults", return_value=cfg):
        _cmd_list()

    out = capsys.readouterr().out
    assert "Primary" in out
    assert "anthropic" in out


# ─── munai models add (preset) ───────────────────────────────────────────────

def test_add_preset_prefills_base_url(tmp_path: Path, capsys):
    """Adding a provider via a known preset pre-fills base_url from the preset."""
    from munai.cli.models_cmd import _cmd_add

    config_file = tmp_path / "munai.json"
    config_file.write_text(json.dumps(_make_config()) + "\n", encoding="utf-8")

    # Simulate user pressing Enter to accept all defaults (provider_name, base_url, format, model, key, tools, timeout)
    # then "n" to skip connectivity test
    user_inputs = [
        "groq",           # provider name
        "",               # base_url (accept preset default)
        "",               # api_format (accept default "openai")
        "",               # model (accept preset default)
        "",               # api_key_env (accept preset default "GROQ_API_KEY")
        "",               # supports_tool_calling (accept "y")
        "",               # timeout (accept 120)
        "n",              # run connectivity test? -> no
    ]

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(config_file, _make_config())),
        patch("munai.cli.models_cmd._write_raw_config") as mock_write,
        patch("builtins.input", side_effect=user_inputs),
        patch("munai.cli.models_cmd.asyncio"),
    ):
        _cmd_add(["--preset", "groq"])

    # The write was called — verify the provider dict passed includes groq's base_url
    assert mock_write.called
    written_data = mock_write.call_args[0][1]
    assert "groq" in written_data["models"]["providers"]
    provider_cfg = written_data["models"]["providers"]["groq"]
    assert "groq.com" in provider_cfg["base_url"]


def test_add_preset_warns_missing_key(tmp_path: Path, capsys, monkeypatch):
    """_cmd_add warns when the referenced env var is not set."""
    from munai.cli.models_cmd import _cmd_add

    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    user_inputs = ["groq", "", "", "", "", "", "", "n"]

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", _make_config())),
        patch("munai.cli.models_cmd._write_raw_config"),
        patch("builtins.input", side_effect=user_inputs),
        patch("munai.cli.models_cmd.asyncio"),
    ):
        _cmd_add(["--preset", "groq"])

    out = capsys.readouterr().out
    # Warning should mention the missing env var
    assert "GROQ_API_KEY" in out or "Warning" in out


# ─── munai models add (custom) ───────────────────────────────────────────────

def test_add_custom_provider(tmp_path: Path):
    """Adding a custom provider with explicit values writes correct config."""
    from munai.cli.models_cmd import _cmd_add

    user_inputs = [
        "custom",           # preset name -> unknown preset -> treated as custom
        "my-provider",      # provider name
        "https://api.example.com/v1",  # base_url
        "openai",           # api_format
        "my-model",         # model
        "MY_PROVIDER_KEY",  # api_key_env
        "y",                # supports tool calling
        "60",               # timeout
        "n",                # run test? -> no
    ]

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", _make_config())),
        patch("munai.cli.models_cmd._write_raw_config") as mock_write,
        patch("builtins.input", side_effect=user_inputs),
        patch("munai.cli.models_cmd.asyncio"),
    ):
        _cmd_add([])  # no --preset

    assert mock_write.called
    written_data = mock_write.call_args[0][1]
    assert "my-provider" in written_data["models"]["providers"]
    cfg = written_data["models"]["providers"]["my-provider"]
    assert cfg["base_url"] == "https://api.example.com/v1"
    assert cfg["model"] == "my-model"
    assert cfg["api_key_env"] == "MY_PROVIDER_KEY"
    assert cfg["timeout_seconds"] == 60


# ─── munai models remove ─────────────────────────────────────────────────────

def test_remove_provider_deletes_from_config(tmp_path: Path, capsys):
    """_cmd_remove removes a non-primary provider and updates config."""
    from munai.cli.models_cmd import _cmd_remove

    raw = _make_config(providers={
        "anthropic": {"name": "anthropic", "model": "claude-test", "base_url": "x", "api_format": "anthropic"},
        "groq": {"name": "groq", "model": "llama", "base_url": "y", "api_format": "openai"},
    })
    raw["models"]["primary"] = "anthropic"

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", raw)),
        patch("munai.cli.models_cmd._write_raw_config") as mock_write,
    ):
        _cmd_remove("groq")

    written_data = mock_write.call_args[0][1]
    assert "groq" not in written_data["models"]["providers"]
    assert "groq" not in written_data["models"]["fallback"]


def test_remove_primary_provider_exits(tmp_path: Path):
    """_cmd_remove refuses to remove the primary provider."""
    from munai.cli.models_cmd import _cmd_remove

    raw = _make_config()

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", raw)),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_remove("anthropic")  # anthropic is primary

    assert exc_info.value.code == 1


def test_remove_nonexistent_provider_exits(tmp_path: Path):
    """_cmd_remove exits with error for unknown provider name."""
    from munai.cli.models_cmd import _cmd_remove

    raw = _make_config()

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", raw)),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_remove("does-not-exist")

    assert exc_info.value.code == 1


# ─── munai models set-primary ─────────────────────────────────────────────────

def test_set_primary_updates_config(tmp_path: Path, capsys):
    """_cmd_set_primary writes the new primary name to config."""
    from munai.cli.models_cmd import _cmd_set_primary

    raw = _make_config(providers={
        "anthropic": {"name": "anthropic", "model": "c", "base_url": "a", "api_format": "anthropic"},
        "groq": {"name": "groq", "model": "l", "base_url": "b", "api_format": "openai"},
    })
    raw["models"]["primary"] = "anthropic"

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", raw)),
        patch("munai.cli.models_cmd._write_raw_config") as mock_write,
    ):
        _cmd_set_primary("groq")

    written_data = mock_write.call_args[0][1]
    assert written_data["models"]["primary"] == "groq"


def test_set_primary_nonexistent_exits(tmp_path: Path):
    """_cmd_set_primary exits with error for unknown provider name."""
    from munai.cli.models_cmd import _cmd_set_primary

    raw = _make_config()

    with (
        patch("munai.cli.models_cmd._load_raw_config", return_value=(tmp_path / "cfg.json", raw)),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_set_primary("no-such-provider")

    assert exc_info.value.code == 1


# ─── munai models test ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_test_openai_format_success(capsys, monkeypatch):
    """_test_one_raw prints success on HTTP 200 from an OpenAI-format provider."""
    from munai.cli.models_cmd import _test_one_raw

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    provider = {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_format": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "model": "gpt-4o",
        "timeout_seconds": 30,
        "extra_headers": {},
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_one_raw(provider, name="openai")

    assert result is True
    out = capsys.readouterr().out
    assert "✓" in out
    assert "openai" in out


@pytest.mark.asyncio
async def test_test_anthropic_format_sends_messages_endpoint(monkeypatch):
    """_test_one_raw POSTs to /messages for Anthropic-format providers."""
    from munai.cli.models_cmd import _test_one_raw

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    provider = {
        "name": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_format": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "api_key_header": "x-api-key",
        "api_key_prefix": "",
        "model": "claude-sonnet-4-5-20250929",
        "timeout_seconds": 30,
        "extra_headers": {},
    }

    captured_url: list[str] = []

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def mock_post(url, **kwargs):
        captured_url.append(url)
        return mock_resp

    mock_session = MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await _test_one_raw(provider, name="anthropic")

    assert len(captured_url) == 1
    assert captured_url[0].endswith("/messages")


@pytest.mark.asyncio
async def test_test_failure_401_prints_error(capsys, monkeypatch):
    """_test_one_raw prints failure message on HTTP 401."""
    from munai.cli.models_cmd import _test_one_raw

    monkeypatch.setenv("DEEPSEEK_API_KEY", "bad-key")

    provider = {
        "name": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_format": "openai",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "model": "deepseek-chat",
        "timeout_seconds": 30,
        "extra_headers": {},
    }

    mock_resp = MagicMock()
    mock_resp.status = 401
    mock_resp.text = AsyncMock(return_value="Unauthorized")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_one_raw(provider, name="deepseek")

    assert result is False
    out = capsys.readouterr().out
    assert "✗" in out
    assert "401" in out


@pytest.mark.asyncio
async def test_test_local_unreachable_connection_error(capsys, monkeypatch):
    """_test_one_raw prints failure on connection error (e.g., Ollama not running)."""
    import aiohttp
    from munai.cli.models_cmd import _test_one_raw

    provider = {
        "name": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_format": "openai",
        "api_key_env": None,
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "model": "qwen3:8b",
        "timeout_seconds": 30,
        "extra_headers": {},
    }

    # The error must be raised when entering the response context manager,
    # which is what aiohttp does for connection failures.
    mock_resp_cm = MagicMock()
    mock_resp_cm.__aenter__ = AsyncMock(
        side_effect=aiohttp.ClientConnectorError(
            MagicMock(),  # connection_key
            OSError("Connection refused"),
        )
    )
    mock_resp_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp_cm)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_one_raw(provider, name="ollama")

    assert result is False
    out = capsys.readouterr().out
    assert "✗" in out
    assert "ollama" in out
