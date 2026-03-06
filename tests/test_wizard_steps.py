"""Unit tests for individual wizard step handlers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from munai.cli.wizard_state import WizardState
from munai.cli.wizard_ui import WizardUI


# ── UI factory ────────────────────────────────────────────────────────────────

def _ui(interactive: bool = False) -> WizardUI:
    """Return a WizardUI instance. Non-interactive by default for unit tests."""
    ui = WizardUI(interactive=interactive)
    ui._console = MagicMock()  # suppress all console output in tests
    return ui


def _state(**kwargs) -> WizardState:
    return WizardState(**kwargs)


# ── step_preflight ─────────────────────────────────────────────────────────────

def test_preflight_sets_existing_config_flag(tmp_path: Path):
    """existing_config becomes True when munai.json already exists."""
    from munai.cli.wizard_steps import step_preflight

    config_file = tmp_path / "munai.json"
    config_file.write_text("{}", encoding="utf-8")

    state = _state()
    ui = _ui()

    with (
        patch("munai.config.MUNAI_DIR", tmp_path),
        patch("munai.config.CONFIG_PATH", config_file),
    ):
        result = step_preflight(state, ui)

    assert result.existing_config is True


def test_preflight_reset_deletes_config(tmp_path: Path):
    """--reset causes existing config to be deleted."""
    from munai.cli.wizard_steps import step_preflight

    config_file = tmp_path / "munai.json"
    config_file.write_text("{}", encoding="utf-8")
    assert config_file.exists()

    state = _state(reset=True)
    ui = _ui()

    with (
        patch("munai.config.MUNAI_DIR", tmp_path),
        patch("munai.config.CONFIG_PATH", config_file),
    ):
        result = step_preflight(state, ui)

    assert not config_file.exists()
    assert result.existing_config is False


# ── step_security ─────────────────────────────────────────────────────────────

def test_security_warning_continue(tmp_path: Path):
    """Selecting 'Yes, continue' should not raise or exit."""
    from munai.cli.wizard_steps import step_security

    ui = _ui()
    ui.ask_select = MagicMock(return_value="Yes, continue")
    ui.section_header = MagicMock()

    state = _state()
    result = step_security(state, ui)
    assert result is state


def test_security_warning_exit_calls_sys_exit(tmp_path: Path):
    """Selecting 'No, exit' should call sys.exit(0)."""
    from munai.cli.wizard_steps import step_security

    ui = _ui()
    ui.ask_select = MagicMock(return_value="No, exit")
    ui.section_header = MagicMock()

    state = _state()
    with pytest.raises(SystemExit) as exc_info:
        step_security(state, ui)
    assert exc_info.value.code == 0


# ── step_setup_mode ────────────────────────────────────────────────────────────

def test_setup_mode_quickstart():
    from munai.cli.wizard_steps import step_setup_mode

    ui = _ui()
    ui.ask_select = MagicMock(return_value="QuickStart (safe defaults, minimal prompts)")

    state = _state()
    result = step_setup_mode(state, ui)
    assert result.flow == "quickstart"


def test_setup_mode_advanced():
    from munai.cli.wizard_steps import step_setup_mode

    ui = _ui()
    ui.ask_select = MagicMock(
        return_value="Advanced (full control: port, bind, auth, all options)"
    )

    state = _state()
    result = step_setup_mode(state, ui)
    assert result.flow == "advanced"


# ── step_model_provider ────────────────────────────────────────────────────────

def test_step_model_provider_anthropic_sets_config():
    """Non-interactive anthropic selection builds correct provider config."""
    from munai.cli.wizard_steps import step_model_provider

    state = _state(provider_name="anthropic", model="claude-test")
    ui = _ui(interactive=False)
    ui._console = MagicMock()

    with patch("munai.cli.wizard_steps._run_connectivity_test", return_value=True):
        result = step_model_provider(state, ui)

    assert result.config["models"]["primary"] == "anthropic"
    assert "anthropic" in result.config["models"]["providers"]
    assert result.config["models"]["providers"]["anthropic"]["model"] == "claude-test"


def test_step_model_provider_ollama_no_key_env():
    """Ollama provider has api_key_env = None in built config."""
    from munai.cli.wizard_steps import step_model_provider

    state = _state(provider_name="ollama", model="llama3")
    ui = _ui(interactive=False)
    ui._console = MagicMock()

    with patch("munai.cli.wizard_steps._run_connectivity_test", return_value=True):
        result = step_model_provider(state, ui)

    provider_cfg = result.config["models"]["providers"]["ollama"]
    assert provider_cfg.get("api_key_env") is None


def test_step_model_provider_skip_returns_unchanged():
    """Selecting 'skip' does not populate config."""
    from munai.cli.wizard_steps import step_model_provider
    from munai.cli.wizard_presets import WIZARD_PROVIDER_LABELS

    skip_label = WIZARD_PROVIDER_LABELS["skip"]
    state = _state()
    ui = _ui(interactive=True)
    ui._console = MagicMock()
    ui.ask_select = MagicMock(return_value=skip_label)

    result = step_model_provider(state, ui)
    assert result.provider_name == "skip"
    assert result.config.get("models") is None


# ── step_channels ──────────────────────────────────────────────────────────────

def test_step_channels_skip_channels_flag():
    """skip_channels=True returns without prompting."""
    from munai.cli.wizard_steps import step_channels

    state = _state(skip_channels=True)
    ui = _ui()
    ui.ask_checkbox = MagicMock()

    result = step_channels(state, ui)
    ui.ask_checkbox.assert_not_called()
    assert result.channels == ["webchat"]


def test_step_channels_non_interactive_no_telegram():
    """Non-interactive without Telegram returns webchat only."""
    from munai.cli.wizard_steps import step_channels

    state = _state()
    ui = _ui(interactive=False)
    ui._console = MagicMock()

    result = step_channels(state, ui)
    assert result.channels == ["webchat"]
    assert "telegram" not in result.channels


# ── step_write_config ──────────────────────────────────────────────────────────

def test_step_write_config_creates_munai_json(tmp_path: Path):
    """step_write_config writes munai.json to the given path."""
    from munai.cli.wizard_steps import step_write_config

    config_path = tmp_path / "munai.json"
    state = _state(
        provider_name="anthropic",
        model="claude-test",
        config={
            "models": {
                "primary": "anthropic",
                "fallback": [],
                "heartbeat": None,
                "providers": {
                    "anthropic": {
                        "name": "anthropic",
                        "model": "claude-test",
                        "base_url": "https://api.anthropic.com/v1",
                        "api_key_env": "ANTHROPIC_API_KEY",
                    }
                },
            }
        },
    )
    ui = _ui()

    result = step_write_config(state, ui, config_path=config_path)

    assert config_path.exists()
    cfg = json.loads(config_path.read_text())
    assert cfg["models"]["primary"] == "anthropic"
    assert "_wizard" in cfg


def test_step_write_config_creates_env_file(tmp_path: Path):
    """When env_vars are present, .env file is written."""
    from munai.cli.wizard_steps import step_write_config

    config_path = tmp_path / "munai.json"
    env_path = tmp_path / ".env"
    state = _state(
        provider_name="anthropic",
        model="claude-test",
        env_vars={"ANTHROPIC_API_KEY": "sk-secret"},
        config={
            "models": {
                "primary": "anthropic",
                "fallback": [],
                "heartbeat": None,
                "providers": {"anthropic": {"name": "anthropic", "model": "claude-test"}},
            }
        },
    )
    ui = _ui()

    step_write_config(state, ui, config_path=config_path, env_path=env_path)

    assert env_path.exists()
    content = env_path.read_text()
    assert "ANTHROPIC_API_KEY=sk-secret" in content


# ── step_gateway ──────────────────────────────────────────────────────────────

def test_step_gateway_sets_port():
    from munai.cli.wizard_steps import step_gateway

    state = _state()
    ui = _ui(interactive=True)
    ui._console = MagicMock()

    # Non-interactive fallback (ask_text returns default)
    ui.interactive = False

    result = step_gateway(state, ui)
    assert result.gateway_port == 18700  # default


def test_step_gateway_custom_port():
    from munai.cli.wizard_steps import step_gateway

    state = _state()
    ui = _ui(interactive=True)
    ui._console = MagicMock()
    ui.ask_text = MagicMock(side_effect=["9999", "90"])  # port then audit retention
    ui.ask_select = MagicMock(
        side_effect=[
            "Loopback (127.0.0.1) — local only, most secure",  # bind
            "Every 30 minutes (default)",                        # heartbeat
            "Strict (shell commands require approval, files restricted to workspace)",
            "Enabled (recommended, 90 day retention)",
        ]
    )

    result = step_gateway(state, ui)
    assert result.gateway_port == 9999
