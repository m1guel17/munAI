"""Main entry point for 'munai onboard'.

Parses CLI arguments, builds initial WizardState, runs the wizard step
sequence, and handles top-level KeyboardInterrupt for a clean exit.
"""
from __future__ import annotations

import argparse
import sys

from .wizard_state import WizardState
from .wizard_ui import WizardUI


def onboard_main(args: list[str]) -> None:
    """Entry point called by munai main."""
    opts = _parse_args(args)
    state = _build_state_from_opts(opts)
    ui = WizardUI(interactive=not opts.non_interactive)
    try:
        _run_wizard(state, opts, ui)
    except KeyboardInterrupt:
        print("\n│\n└  Onboarding cancelled. Run 'munai onboard' to try again.\n")
        sys.exit(0)


# ── Argument parsing ───────────────────────────────────────────────────────────

def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="munai onboard",
        description="Interactive first-run setup wizard for munAI.",
        add_help=True,
    )
    parser.add_argument(
        "--flow",
        choices=["quickstart", "advanced"],
        default=None,
        help="Skip mode selection: 'quickstart' (default) or 'advanced'.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing config and workspace, then start fresh.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        dest="non_interactive",
        help="Disable all prompts; use flag values only (for CI/scripting).",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Provider preset name (e.g. anthropic, openai, ollama) or 'custom'.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the default model ID for the selected provider.",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        dest="api_key_env",
        help="Environment variable name that holds the API key (used for custom providers).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Gateway port (default: 18700).",
    )
    parser.add_argument(
        "--bind",
        default=None,
        help="Gateway bind: 'loopback' (127.0.0.1), 'lan' (0.0.0.0), or a custom IP.",
    )
    parser.add_argument(
        "--install-daemon",
        action="store_true",
        dest="install_daemon",
        help="Install and start the gateway as a background service (systemd/launchd).",
    )
    parser.add_argument(
        "--skip-channels",
        action="store_true",
        dest="skip_channels",
        help="Skip channel configuration (Telegram, etc.).",
    )
    return parser.parse_args(args)


# ── State initialisation ───────────────────────────────────────────────────────

def _build_state_from_opts(opts: argparse.Namespace) -> WizardState:
    state = WizardState()

    if opts.flow:
        state.flow = opts.flow
    if opts.reset:
        state.reset = True
    if opts.provider:
        state.provider_name = opts.provider
    if opts.model:
        state.model = opts.model
    if opts.port:
        state.gateway_port = opts.port
    if opts.bind:
        _bind_map = {"loopback": "127.0.0.1", "lan": "0.0.0.0"}
        state.gateway_bind = _bind_map.get(opts.bind, opts.bind)
    if opts.install_daemon:
        state.start_gateway = "daemon"
    if opts.skip_channels:
        state.skip_channels = True

    # Non-interactive validation
    if opts.non_interactive:
        if not opts.provider:
            print(
                "Error: --non-interactive requires --provider.\n"
                "Example: munai onboard --non-interactive --provider anthropic "
                "--model claude-sonnet-4-6 --api-key-env ANTHROPIC_API_KEY",
                file=sys.stderr,
            )
            sys.exit(1)

    return state


# ── Wizard runner ──────────────────────────────────────────────────────────────

def _run_wizard(
    state: WizardState,
    opts: argparse.Namespace,
    ui: WizardUI,
) -> None:
    from .wizard_steps import (
        step_preflight,
        step_security,
        step_setup_mode,
        step_model_provider,
        step_channels,
        step_gateway,
        step_workspace,
        step_write_config,
        step_start_gateway,
        step_summary,
    )

    ui.wizard_header("0.1.0")

    # (step_fn, advanced_only)
    all_steps = [
        (step_preflight, False),
        (step_security, False),
        (step_setup_mode, False),
        (step_model_provider, False),
        (step_channels, False),
        (step_gateway, True),      # skipped in QuickStart
        (step_workspace, False),
        (step_write_config, False),
        (step_start_gateway, False),
        (step_summary, False),
    ]

    for step_fn, advanced_only in all_steps:
        # Skip gateway config step in quickstart
        if advanced_only and state.flow == "quickstart":
            continue
        # Skip setup_mode prompt if --flow was given on the CLI
        if step_fn is step_setup_mode and opts.flow:
            continue

        state = step_fn(state, ui)

        # Special: "Keep existing → skip to channels" chosen in preflight
        if state.flow == "_skip_to_channels":
            state.flow = "quickstart"
            state = step_channels(state, ui)
            state = step_workspace(state, ui)
            state = step_write_config(state, ui)
            state = step_summary(state, ui)
            break

    ui.wizard_footer()
