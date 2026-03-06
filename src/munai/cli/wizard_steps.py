"""Individual step handlers for the onboarding wizard.

Each step is a plain function:  step_*(state, ui) -> WizardState

Steps use asyncio.run() internally for aiohttp calls so the top-level
wizard runner can stay synchronous.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .wizard_state import WizardState
    from .wizard_ui import WizardUI

from .wizard_presets import PROVIDER_PRESETS, WIZARD_PROVIDERS, WIZARD_PROVIDER_LABELS


# ─── Step 0: Pre-flight ────────────────────────────────────────────────────────

def step_preflight(state: "WizardState", ui: "WizardUI") -> "WizardState":
    from ..config import MUNAI_DIR, CONFIG_PATH

    ui.section_header("Pre-flight", ["Checking prerequisites ..."])

    # Python version
    ver = sys.version_info
    if ver < (3, 12):
        ui.error(f"Python {ver.major}.{ver.minor} is too old. munAI requires Python 3.12+.")
        sys.exit(1)
    ui.success(f"Python {ver.major}.{ver.minor}.{ver.micro}")

    # ~/.munai/ directory
    MUNAI_DIR.mkdir(parents=True, exist_ok=True)
    ui.success("~/.munai/ directory ready")

    # Existing config
    if CONFIG_PATH.exists():
        state.existing_config = True
        if state.reset:
            CONFIG_PATH.unlink()
            ui.success("Existing configuration removed (--reset)")
            state.existing_config = False
        elif ui.interactive:
            choice = ui.ask_select(
                "Config file found. What do you want to do?",
                choices=[
                    "Keep existing and skip to channels",
                    "Update values",
                    "Reset everything",
                ],
                default="Update values",
            )
            if choice == "Keep existing and skip to channels":
                state.flow = "_skip_to_channels"
            elif choice == "Reset everything":
                CONFIG_PATH.unlink()
                state.existing_config = False
                ui.success("Existing configuration removed")
            # else "Update values" → continue
        else:
            ui.rail("○ Existing configuration found")
    else:
        ui.rail("○ No existing configuration found")

    ui.rail_blank()
    return state


# ─── Step 1: Security Warning ─────────────────────────────────────────────────

def step_security(state: "WizardState", ui: "WizardUI") -> "WizardState":
    ui.section_header("Security", [
        "Security warning — please read.",
        "",
        "munAI is a self-hosted AI assistant. When tools are enabled,",
        "it can read/write files and run shell commands on this",
        "machine. Treat incoming messages as untrusted input.",
        "",
        "• Shell commands require your approval by default",
        "• File access is restricted to the workspace directory",
        "• All tool executions are logged to the audit trail",
        "• Run 'munai doctor' regularly to check for issues",
    ])

    choice = ui.ask_select(
        "Do you understand and want to continue?",
        choices=["Yes, continue", "No, exit"],
        default="Yes, continue",
    )
    if choice == "No, exit":
        print("│")
        print("└  Goodbye.")
        sys.exit(0)

    return state


# ─── Step 2: Setup Mode ────────────────────────────────────────────────────────

def step_setup_mode(state: "WizardState", ui: "WizardUI") -> "WizardState":
    choice = ui.ask_select(
        "Setup mode",
        choices=[
            "QuickStart (safe defaults, minimal prompts)",
            "Advanced (full control: port, bind, auth, all options)",
        ],
        default="QuickStart (safe defaults, minimal prompts)",
    )
    if choice and "Advanced" in choice:
        state.flow = "advanced"
    else:
        state.flow = "quickstart"
    return state


# ─── Step 3: Model / Auth Provider ────────────────────────────────────────────

def step_model_provider(state: "WizardState", ui: "WizardUI") -> "WizardState":
    # Non-interactive with provider already set → build config directly
    if not ui.interactive and state.provider_name:
        _build_provider_config(state, ui)
        return state

    # Build choice list from WIZARD_PROVIDERS
    choices = [WIZARD_PROVIDER_LABELS.get(p, p) for p in WIZARD_PROVIDERS]
    label = ui.ask_select(
        "Model / auth provider",
        choices=choices,
        default=choices[0],
    )

    # Map label → preset name
    label_to_name = {v: k for k, v in WIZARD_PROVIDER_LABELS.items()}
    state.provider_name = label_to_name.get(label, "skip")

    if state.provider_name == "skip":
        return state

    _build_provider_config(state, ui)
    return state


def _build_provider_config(state: "WizardState", ui: "WizardUI") -> None:
    name = state.provider_name
    if name == "custom":
        _configure_custom_provider(state, ui)
        return

    preset = dict(PROVIDER_PRESETS.get(name, {}))
    is_local = preset.get("api_key_env") is None

    # ── Model selection ──────────────────────────────────────────────────────
    models_available = preset.get("models_available", [])

    # In non-interactive mode, honor --model flag directly
    if not ui.interactive and state.model:
        pass  # state.model already set by --model flag; skip all selection prompts
    elif models_available:
        default_model = state.model if state.model in models_available else models_available[0]
        model_choices = models_available + ["Enter manually"]
        chosen = ui.ask_select(
            "Choose a default model",
            choices=model_choices,
            default=default_model,
        )
        if chosen == "Enter manually":
            state.model = ui.ask_text("Model ID", default=preset.get("model", ""))
        else:
            state.model = chosen
    elif name == "ollama":
        available = _probe_ollama(ui)
        if available:
            available_choices = available + ["Enter a model name manually"]
            chosen = ui.ask_select(
                "Ollama is running. Choose a model:",
                choices=available_choices,
                default=available[0],
            )
            if chosen == "Enter a model name manually":
                state.model = ui.ask_text("Model name", default=preset.get("model", "qwen3:8b"))
            else:
                state.model = chosen
        else:
            state.model = ui.ask_text(
                "Model name (Ollama not reachable — enter manually)",
                default=state.model or preset.get("model", "qwen3:8b"),
            )
    else:
        state.model = ui.ask_text("Model ID", default=state.model or preset.get("model", ""))

    if not state.model:
        state.model = preset.get("model", "")

    # ── API key (cloud providers only) ────────────────────────────────────────
    if not is_local:
        env_var_name = preset.get("api_key_env", f"{name.upper()}_API_KEY")
        existing_key = os.environ.get(env_var_name)

        auth_choice = ui.ask_select(
            "How do you want to authenticate?",
            choices=[
                "API key (paste or set env var)",
                "Environment variable reference (key stored in env, not config)",
            ],
            default="API key (paste or set env var)",
        )

        if auth_choice and "paste" in auth_choice:
            hint = (
                f"(already set in env — press Enter to keep)"
                if existing_key
                else f"(will be saved to ~/.munai/.env as {env_var_name})"
            )
            ui.rail(f"hint: {hint}")
            key_value = ui.ask_text(
                f"Enter your API key (or press Enter to use {env_var_name} from env)",
                password=True,
            )
            if key_value:
                state.env_vars[env_var_name] = key_value
            elif not existing_key:
                ui.warning(
                    f"{env_var_name} is not set. You'll need to set it before starting."
                )
        else:
            if not existing_key:
                ui.warning(
                    f"{env_var_name} is not set in environment. "
                    "Set it before running 'munai gateway'."
                )

    # ── Build provider dict for config ────────────────────────────────────────
    provider_cfg: dict = {"name": name}
    # Start from preset, then override model
    provider_cfg.update({k: v for k, v in preset.items() if k != "models_available"})
    provider_cfg["model"] = state.model

    state.config.setdefault("models", {}).setdefault("providers", {})[name] = provider_cfg
    state.config["models"]["primary"] = name
    state.config["models"].setdefault("fallback", [])
    state.config["models"].setdefault("heartbeat", None)

    # ── Connectivity test ─────────────────────────────────────────────────────
    _run_connectivity_test(state, ui, provider_cfg)


def _configure_custom_provider(state: "WizardState", ui: "WizardUI") -> None:
    base_url = ui.ask_text(
        "Base URL (must include /v1 path)",
        default="https://api.example.com/v1",
    )
    api_key_env_raw = ui.ask_text(
        "API key environment variable name (or 'none' for local)",
        default="MY_PROVIDER_API_KEY",
    )
    api_key_env: str | None = (
        None if api_key_env_raw.lower() in ("none", "") else api_key_env_raw
    )
    model = ui.ask_text("Model ID", default=state.model or "")
    tools_choice = ui.ask_select(
        "Does this provider support function/tool calling?",
        choices=["Yes", "No (will use prompt-based tool instructions)"],
        default="Yes",
    )
    supports_tools = (tools_choice == "Yes")

    state.model = model
    state.provider_name = "custom"

    provider_cfg: dict = {
        "name": "custom",
        "base_url": base_url,
        "model": model,
        "supports_tool_calling": supports_tools,
    }
    if api_key_env:
        provider_cfg["api_key_env"] = api_key_env

    state.config.setdefault("models", {}).setdefault("providers", {})["custom"] = provider_cfg
    state.config["models"]["primary"] = "custom"
    state.config["models"].setdefault("fallback", [])
    state.config["models"].setdefault("heartbeat", None)

    _run_connectivity_test(state, ui, provider_cfg)


def _probe_ollama(ui: "WizardUI") -> list[str]:
    """Try to list models from the local Ollama server. Returns [] on failure."""
    import aiohttp

    async def _get():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://127.0.0.1:11434/v1/models",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [
                            m.get("id", m.get("name", ""))
                            for m in data.get("data", [])
                            if m.get("id") or m.get("name")
                        ]
        except Exception:
            pass
        return []

    with ui.spinner("Checking Ollama at http://127.0.0.1:11434"):
        models = asyncio.run(_get())

    if not models:
        ui.warning(
            "Ollama is not running at the default URL. "
            "Start it with 'ollama serve' and try again, or enter a model name manually."
        )
    return models


def _run_connectivity_test(
    state: "WizardState", ui: "WizardUI", provider_cfg: dict
) -> bool:
    """Run connectivity test with retry logic (interactive) or warn-and-continue (non-interactive)."""
    from ..cli.models_cmd import _test_one_raw

    # Inject keys the user just entered so _test_one_raw can see them
    for k, v in state.env_vars.items():
        os.environ.setdefault(k, v)

    while True:
        with ui.spinner(f"Testing connectivity to {provider_cfg.get('name', '?')}"):
            ok = asyncio.run(_test_one_raw(provider_cfg))

        if ok:
            return True

        if not ui.interactive:
            ui.warning(
                "Connectivity test failed. Fix API key / URL before running 'munai gateway'."
            )
            return False

        retry = ui.ask_select(
            "What do you want to do?",
            choices=[
                "Retry",
                "Continue anyway (fix later)",
                "Choose a different provider",
            ],
            default="Continue anyway (fix later)",
        )
        if retry == "Retry":
            continue
        elif retry == "Choose a different provider":
            state.provider_name = None
            step_model_provider(state, ui)
        return False


# ─── Step 4: Channels ─────────────────────────────────────────────────────────

def step_channels(state: "WizardState", ui: "WizardUI") -> "WizardState":
    if state.skip_channels:
        ui.rail("  Channels: skipped (--skip-channels)")
        return state

    choices = [
        "WebChat (browser UI, always available)",
        "Telegram",
        "Skip channels for now",
    ]
    selected = ui.ask_checkbox(
        "Connect messaging channels (select all that apply)",
        choices=choices,
        defaults=["WebChat (browser UI, always available)"],
    )

    if selected is None:
        selected = ["WebChat (browser UI, always available)"]

    state.channels = ["webchat"]
    if "Telegram" in selected:
        _configure_telegram(state, ui)

    return state


def _configure_telegram(state: "WizardState", ui: "WizardUI") -> None:
    token = ui.ask_text(
        "Telegram bot token (from @BotFather, starts with digits:)",
        password=True,
    )
    if not token:
        return

    import aiohttp

    async def _test_token(tok: str) -> str | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.telegram.org/bot{tok}/getMe",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result", {}).get("username")
        except Exception:
            pass
        return None

    with ui.spinner("Testing Telegram bot token"):
        bot_username = asyncio.run(_test_token(token))

    if bot_username:
        ui.success(f"Bot @{bot_username} is valid")
        env_var = "TELEGRAM_BOT_TOKEN"
        state.env_vars[env_var] = token
        state.telegram_token_env = env_var
        state.channels.append("telegram")
    else:
        ui.warning("Telegram token validation failed. Check the token.")
        if not ui.interactive:
            return

    # DM policy
    policy_choice = ui.ask_select(
        "Who can message this bot?",
        choices=[
            "Pairing mode (unknown senders get a pairing code)",
            "Allowlist only (specify Telegram user IDs)",
            "Open (anyone can message — NOT recommended)",
        ],
        default="Pairing mode (unknown senders get a pairing code)",
    )
    if policy_choice and "Allowlist" in policy_choice:
        state.telegram_dm_policy = "closed"
        ids_raw = ui.ask_text(
            "Enter Telegram user IDs (comma-separated)", default=""
        )
        state.telegram_allow_from = [
            x.strip() for x in ids_raw.split(",") if x.strip()
        ]
    elif policy_choice and "Open" in policy_choice:
        state.telegram_dm_policy = "open"
    else:
        state.telegram_dm_policy = "pairing"


# ─── Step 5: Gateway Configuration (advanced only) ────────────────────────────

def step_gateway(state: "WizardState", ui: "WizardUI") -> "WizardState":
    # Port
    port_str = ui.ask_text("Gateway port", default=str(state.gateway_port))
    try:
        state.gateway_port = int(port_str) if port_str else 18700
    except ValueError:
        state.gateway_port = 18700

    # Bind address
    bind_choice = ui.ask_select(
        "Gateway bind address",
        choices=[
            "Loopback (127.0.0.1) — local only, most secure",
            "LAN (0.0.0.0) — accessible on local network",
            "Custom IP",
        ],
        default="Loopback (127.0.0.1) — local only, most secure",
    )
    if bind_choice and "LAN" in bind_choice:
        state.gateway_bind = "0.0.0.0"
    elif bind_choice and "Custom" in bind_choice:
        state.gateway_bind = ui.ask_text("Custom bind IP", default="0.0.0.0")
    else:
        state.gateway_bind = "127.0.0.1"

    # Auth (non-loopback only)
    if state.gateway_bind != "127.0.0.1":
        ui.warning("Non-loopback bind requires authentication.")
        auth_choice = ui.ask_select(
            "Gateway authentication",
            choices=["Auto-generate token (recommended)", "Set a custom token"],
            default="Auto-generate token (recommended)",
        )
        if auth_choice and "custom" in auth_choice.lower():
            state.gateway_token = ui.ask_text("Gateway auth token", password=True)
        else:
            state.gateway_token = secrets.token_hex(32)
            ui.success("Generated gateway token")

    # Heartbeat
    hb_choice = ui.ask_select(
        "Heartbeat interval",
        choices=["Every 30 minutes (default)", "Every hour", "Disabled"],
        default="Every 30 minutes (default)",
    )
    if hb_choice and "hour" in hb_choice:
        state.heartbeat_enabled = True
        state.heartbeat_interval = 60
    elif hb_choice and "Disabled" in hb_choice:
        state.heartbeat_enabled = False
    else:
        state.heartbeat_enabled = True
        state.heartbeat_interval = 30

    # Tool policy
    tool_choice = ui.ask_select(
        "Tool policy",
        choices=[
            "Strict (shell commands require approval, files restricted to workspace)",
            "Moderate (approve shell once per session, files restricted to workspace)",
            "Permissive (no approval, files anywhere — for advanced users)",
        ],
        default="Strict (shell commands require approval, files restricted to workspace)",
    )
    if tool_choice and "Moderate" in tool_choice:
        state.shell_approval_mode = "once"
        state.workspace_only = True
    elif tool_choice and "Permissive" in tool_choice:
        state.shell_approval_mode = "never"
        state.workspace_only = False
    else:
        state.shell_approval_mode = "always"
        state.workspace_only = True

    # Audit
    audit_choice = ui.ask_select(
        "Audit logging",
        choices=[
            "Enabled (recommended, 90 day retention)",
            "Enabled (custom retention)",
            "Disabled",
        ],
        default="Enabled (recommended, 90 day retention)",
    )
    if audit_choice and "custom" in audit_choice.lower():
        days_str = ui.ask_text("Retention in days", default="90")
        try:
            state.audit_retention = int(days_str)
        except ValueError:
            state.audit_retention = 90
        state.audit_enabled = True
    elif audit_choice and "Disabled" in audit_choice:
        state.audit_enabled = False
    else:
        state.audit_enabled = True
        state.audit_retention = 90

    return state


# ─── Step 6: Workspace Setup ──────────────────────────────────────────────────

def step_workspace(state: "WizardState", ui: "WizardUI") -> "WizardState":
    from ..workspace.bootstrap import ensure_workspace, _DEFAULTS, _SAMPLE_SKILLS

    ws_path = Path(state.workspace_path).expanduser()
    ui.rail_blank()
    ui.rail(f"▪  Creating workspace at {state.workspace_path} ...")
    ui.rail_blank()

    # Snapshot what exists before
    existed_before = {f: (ws_path / f).exists() for f in _DEFAULTS}
    skills_existed = {
        f: (ws_path / "skills" / f).exists() for f in _SAMPLE_SKILLS
    }

    ensure_workspace(ws_path)

    for filename in _DEFAULTS:
        if existed_before[filename]:
            ui.rail(f"  ○ {filename} — already exists")
        else:
            ui.success(filename)

    for filename in _SAMPLE_SKILLS:
        if skills_existed[filename]:
            ui.rail(f"  ○ skills/{filename} — already exists")
        else:
            ui.success(f"skills/{filename}")

    for subdir in ("memory",):
        subdir_path = ws_path / subdir
        if not subdir_path.exists():
            subdir_path.mkdir(parents=True, exist_ok=True)
            ui.success(f"{subdir}/")
        else:
            ui.rail(f"  ○ {subdir}/ — already exists")

    ui.rail_blank()
    return state


# ─── Step 7: Write Config ─────────────────────────────────────────────────────

def step_write_config(
    state: "WizardState",
    ui: "WizardUI",
    config_path: Path | None = None,
    env_path: Path | None = None,
) -> "WizardState":
    from ..config import CONFIG_PATH, MUNAI_DIR

    _config_path = config_path or CONFIG_PATH
    _env_path = env_path or (MUNAI_DIR / ".env")

    ui.rail_blank()
    ui.rail("▪  Writing configuration ...")

    cfg = _assemble_config(state)
    _config_path.parent.mkdir(parents=True, exist_ok=True)
    _config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    ui.success(str(_config_path))

    if state.env_vars:
        lines = "".join(f"{k}={v}\n" for k, v in state.env_vars.items())
        _env_path.write_text(lines, encoding="utf-8")
        try:
            os.chmod(_env_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except (AttributeError, NotImplementedError, OSError):
            pass  # Windows doesn't support chmod in the same way
        ui.success(f"{_env_path} (permissions: 600)")

    ui.rail_blank()
    return state


def _assemble_config(state: "WizardState") -> dict:
    """Build the complete config dict from WizardState."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Models section (may have been built incrementally by step_model_provider)
    models_section = dict(state.config.get("models", {}))
    if not models_section.get("primary") and state.provider_name and state.provider_name != "skip":
        preset = dict(PROVIDER_PRESETS.get(state.provider_name, {}))
        provider_cfg = {"name": state.provider_name}
        provider_cfg.update({k: v for k, v in preset.items() if k != "models_available"})
        provider_cfg["model"] = state.model or preset.get("model", "")
        models_section = {
            "primary": state.provider_name,
            "fallback": [],
            "heartbeat": None,
            "providers": {state.provider_name: provider_cfg},
        }

    # Gateway token
    token_env: str | None = None
    if state.gateway_token:
        token_env = "MUNAI_GATEWAY_TOKEN"
        state.env_vars["MUNAI_GATEWAY_TOKEN"] = state.gateway_token

    # Telegram
    telegram_cfg: dict = {"enabled": "telegram" in state.channels}
    if state.telegram_token_env:
        telegram_cfg["bot_token_env"] = state.telegram_token_env
    if state.telegram_dm_policy:
        telegram_cfg["dm_policy"] = state.telegram_dm_policy
    if state.telegram_allow_from:
        telegram_cfg["allow_from"] = state.telegram_allow_from

    return {
        "_wizard": {
            "version": "0.1.0",
            "completed_at": now,
            "flow": state.flow,
        },
        "models": models_section,
        "gateway": {
            "bind": state.gateway_bind,
            "port": state.gateway_port,
            "token_env": token_env,
        },
        "agent": {
            "workspace": state.workspace_path,
        },
        "channels": {
            "webchat": {"enabled": True},
            "telegram": telegram_cfg,
        },
        "heartbeat": {
            "enabled": state.heartbeat_enabled,
            "interval_minutes": state.heartbeat_interval,
        },
        "tools": {
            "shell_approval_mode": state.shell_approval_mode,
            "workspace_only": state.workspace_only,
        },
        "audit": {
            "enabled": state.audit_enabled,
            "retention_days": state.audit_retention,
        },
    }


# ─── Step 8: Start Gateway ─────────────────────────────────────────────────────

def step_start_gateway(state: "WizardState", ui: "WizardUI") -> "WizardState":
    # Non-interactive: use --install-daemon / --start-foreground flags
    if state.start_gateway == "daemon":
        from .daemon import install_daemon
        with ui.spinner("Installing munAI gateway as a system service"):
            install_daemon(state, ui)
        return state
    if state.start_gateway == "foreground":
        _start_foreground(state, ui)
        return state

    choice = ui.ask_select(
        "Start the gateway now?",
        choices=[
            "Yes, start in foreground (see live logs)",
            "Yes, install as background service (systemd/launchd)",
            "No, I'll start it later",
        ],
        default="No, I'll start it later",
    )

    if choice and "foreground" in choice.lower():
        _start_foreground(state, ui)
    elif choice and "background" in choice.lower():
        from .daemon import install_daemon
        with ui.spinner("Installing munAI gateway as a system service"):
            ok = install_daemon(state, ui)
        if ok:
            ui.success(f"Gateway is running at ws://{state.gateway_bind}:{state.gateway_port}")

    return state


def _start_foreground(state: "WizardState", ui: "WizardUI") -> None:
    ui.rail_blank()
    ui.success(f"Gateway is running at ws://{state.gateway_bind}:{state.gateway_port}")
    ui.success(f"WebChat available at http://{state.gateway_bind}:{state.gateway_port}/")
    ui.rail_blank()
    ui.rail("  Press Ctrl+C to stop.")
    ui.rail_blank()
    from ..cli.gateway_cmd import gateway_main
    gateway_main([])


# ─── Step 9: Summary ──────────────────────────────────────────────────────────

def step_summary(state: "WizardState", ui: "WizardUI") -> "WizardState":
    provider_display = state.provider_name or "(none)"
    if state.model:
        provider_display = f"{provider_display.capitalize()} ({state.model})"

    telegram_display = "(not configured)"
    if "telegram" in state.channels:
        telegram_display = f"configured ({state.telegram_dm_policy} mode)"

    audit_display = (
        f"enabled ({state.audit_retention} day retention)"
        if state.audit_enabled
        else "disabled"
    )

    ui.section_header("Setup complete!", [
        f"✓ Provider: {provider_display}",
        f"✓ Gateway:  ws://{state.gateway_bind}:{state.gateway_port}",
        f"✓ WebChat:  http://{state.gateway_bind}:{state.gateway_port}/",
        f"✓ Telegram: {telegram_display}",
        f"✓ Workspace: {state.workspace_path}",
        f"✓ Audit: {audit_display}",
        "",
        "Next steps:",
        f"  • Open http://{state.gateway_bind}:{state.gateway_port}/ to chat via browser",
        "  • Edit ~/.munai/workspace/SOUL.md to set personality",
        "  • Run 'munai doctor' to verify everything is healthy",
    ])
    return state
