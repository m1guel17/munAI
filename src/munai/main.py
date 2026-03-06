"""CLI dispatcher — entry point for the 'munai' command."""
from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _print_help()
        sys.exit(1)

    cmd = args[0]

    if cmd in ("-h", "--help", "help"):
        _print_help()
        return

    if cmd == "gateway":
        from .cli.gateway_cmd import gateway_main
        gateway_main(args[1:])

    elif cmd == "onboard":
        from .cli.onboard import onboard_main
        onboard_main(args[1:])

    elif cmd == "doctor":
        from .cli.doctor_cmd import doctor_main
        doctor_main(args[1:])

    elif cmd == "sessions":
        from .cli.sessions_cmd import sessions_main
        sessions_main(args[1:])

    elif cmd == "audit":
        from .cli.audit_cmd import audit_main
        audit_main(args[1:])

    elif cmd == "skills":
        from .cli.skills_cmd import skills_main
        skills_main(args[1:])

    elif cmd == "models":
        from .cli.models_cmd import models_main
        models_main(args[1:])

    elif cmd == "version":
        print("munai 0.1.0")

    else:
        print(f"Unknown command: {cmd!r}", file=sys.stderr)
        print("Run 'munai help' for usage.", file=sys.stderr)
        sys.exit(1)


def _print_help() -> None:
    print("""\
munai — Personal AI Assistant Platform

Usage:
  munai gateway            Start the Gateway + Web UI (foreground)
  munai onboard            Interactive first-run setup wizard
  munai doctor             Health check (API keys, workspace, services)
  munai models             Manage LLM providers (list/add/remove/set-primary/test)
  munai sessions [<id>]    Browse or inspect past conversation sessions
  munai audit              Tail and filter structured audit log events
  munai skills [<name>]    List workspace skills or show a skill's prompt
  munai version            Show version

Options (all commands):
  -h, --help               Show this help message

Environment variables (can be placed in ~/.munai/.env):
  MUNAI_GATEWAY_TOKEN      Auth token for the gateway WebSocket
                           Required for non-loopback bind and external_app clients
  MUNAI_LOG_LEVEL          Log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
  TELEGRAM_BOT_TOKEN       Telegram bot token (if Telegram channel is enabled)
  <PROVIDER>_API_KEY       LLM provider API key — name set per provider in config
                           e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY

Files:
  ~/.munai/munai.json      Main config (JSON5 — use 'munai models' or edit directly)
  ~/.munai/.env            Secret env vars loaded automatically on startup
  ~/.munai/sessions/       Per-session JSONL conversation history
  ~/.munai/audit/          Daily structured audit logs (JSONL)
  ~/.munai/workspace/      Agent workspace: AGENTS.md, SOUL.md, skills/, etc.

Web UI:  http://127.0.0.1:18700  (after 'munai gateway')
Docs:    https://github.com/munai-assistant/munai
""")
