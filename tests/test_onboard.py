"""Integration tests for the onboarding wizard (non-interactive mode)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from munai.cli.onboard import onboard_main


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args: list[str], munai_dir: Path) -> None:
    """Run onboard_main with config/env redirected to tmp dir."""
    config_path = munai_dir / "munai.json"
    env_path = munai_dir / ".env"
    workspace = munai_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    with (
        patch("munai.config.MUNAI_DIR", munai_dir),
        patch("munai.config.CONFIG_PATH", config_path),
        patch("munai.cli.wizard_steps.step_write_config",
              wraps=_make_patched_write(config_path, env_path)),
        patch("munai.cli.wizard_steps.step_workspace",
              side_effect=lambda s, u: s),
        patch("munai.cli.wizard_steps._run_connectivity_test", return_value=True),
        patch("munai.cli.wizard_steps.step_start_gateway", side_effect=lambda s, u: s),
    ):
        onboard_main(args)


def _make_patched_write(config_path, env_path):
    from munai.cli.wizard_steps import step_write_config as orig

    def _patched(state, ui, **_):
        return orig(state, ui, config_path=config_path, env_path=env_path)

    return _patched


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_non_interactive_anthropic_writes_config(tmp_path: Path):
    """--non-interactive + anthropic preset → munai.json created with correct provider."""
    munai_dir = tmp_path / ".munai"
    munai_dir.mkdir()

    _run(
        [
            "--non-interactive",
            "--provider", "anthropic",
            "--model", "claude-test",
            "--api-key-env", "ANTHROPIC_API_KEY",
            "--skip-channels",
            "--flow", "quickstart",
        ],
        munai_dir,
    )

    config_file = munai_dir / "munai.json"
    assert config_file.exists(), "munai.json was not created"
    cfg = json.loads(config_file.read_text())
    assert cfg["models"]["primary"] == "anthropic"
    assert "anthropic" in cfg["models"]["providers"]
    assert cfg["models"]["providers"]["anthropic"]["model"] == "claude-test"


def test_non_interactive_ollama_no_api_key_env(tmp_path: Path):
    """Ollama preset → api_key_env is None in config."""
    munai_dir = tmp_path / ".munai"
    munai_dir.mkdir()

    _run(
        [
            "--non-interactive",
            "--provider", "ollama",
            "--model", "llama3",
            "--skip-channels",
            "--flow", "quickstart",
        ],
        munai_dir,
    )

    cfg = json.loads((munai_dir / "munai.json").read_text())
    ollama_cfg = cfg["models"]["providers"]["ollama"]
    assert ollama_cfg.get("api_key_env") is None


def test_non_interactive_creates_wizard_metadata(tmp_path: Path):
    """Config written by non-interactive wizard contains _wizard metadata."""
    munai_dir = tmp_path / ".munai"
    munai_dir.mkdir()

    _run(
        [
            "--non-interactive",
            "--provider", "anthropic",
            "--model", "claude-test",
            "--skip-channels",
            "--flow", "quickstart",
        ],
        munai_dir,
    )

    cfg = json.loads((munai_dir / "munai.json").read_text())
    assert "_wizard" in cfg
    assert cfg["_wizard"]["version"] == "0.1.0"
    assert cfg["_wizard"]["flow"] == "quickstart"


def test_reset_flag_overwrites_existing_config(tmp_path: Path):
    """--reset causes existing config to be deleted and rewritten."""
    munai_dir = tmp_path / ".munai"
    munai_dir.mkdir()
    config_file = munai_dir / "munai.json"
    config_file.write_text('{"old": true}', encoding="utf-8")

    _run(
        [
            "--non-interactive",
            "--reset",
            "--provider", "anthropic",
            "--model", "claude-test",
            "--skip-channels",
            "--flow", "quickstart",
        ],
        munai_dir,
    )

    cfg = json.loads(config_file.read_text())
    assert "old" not in cfg
    assert cfg["models"]["primary"] == "anthropic"


def test_missing_provider_exits_with_error(tmp_path: Path, capsys):
    """--non-interactive without --provider should print error and exit 1."""
    with pytest.raises(SystemExit) as exc_info:
        onboard_main(["--non-interactive", "--skip-channels"])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "provider" in captured.err.lower()


def test_ctrl_c_handled_gracefully(tmp_path: Path, capsys):
    """KeyboardInterrupt during wizard is caught and exits cleanly with code 0."""
    munai_dir = tmp_path / ".munai"
    munai_dir.mkdir()

    def _raise(*_args, **_kwargs):
        raise KeyboardInterrupt

    with (
        patch("munai.config.MUNAI_DIR", munai_dir),
        patch("munai.config.CONFIG_PATH", munai_dir / "munai.json"),
        patch("munai.cli.wizard_steps.step_preflight", side_effect=_raise),
        pytest.raises(SystemExit) as exc_info,
    ):
        onboard_main(["--non-interactive", "--provider", "anthropic", "--skip-channels"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "cancelled" in captured.out.lower()
