"""CLI command: munai doctor — health checker."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def run_doctor_checks() -> list[dict]:
    """Run all health checks and return structured results.

    Each result dict has keys: ``label`` (str), ``ok`` (bool), ``detail`` (str).
    """
    raw: list[tuple[str, bool, str]] = []  # (label, passed, detail)

    from pathlib import Path
    from .gateway_cmd import _load_dotenv
    _load_dotenv(Path.home() / ".munai" / ".env")

    from ..config import CONFIG_PATH
    from ..audit.logger import AUDIT_DIR
    from ..agent.session import SESSIONS_DIR

    # ── 1. Config file exists ────────────────────────────────────────────────
    config_exists = CONFIG_PATH.exists()
    raw.append(("Config file exists", config_exists, str(CONFIG_PATH)))

    # ── 2. Config valid ──────────────────────────────────────────────────────
    config = None
    if config_exists:
        try:
            from ..config import load_config
            config = load_config(CONFIG_PATH)
            raw.append(("Config is valid", True, ""))
        except Exception as exc:
            raw.append(("Config is valid", False, str(exc)))
    else:
        raw.append(("Config is valid", False, "config file missing"))

    # ── 3. Primary model API key ─────────────────────────────────────────────
    if config is not None:
        primary_provider = config.models.providers.get(config.models.primary)
        key_env = primary_provider.api_key_env if primary_provider else None
        if key_env is None:
            raw.append(("Primary model API key", True, "no key required (local runtime)"))
        else:
            key_set = bool(os.environ.get(key_env))
            raw.append((
                f"Primary model API key ({key_env})",
                key_set,
                "set" if key_set else f"{key_env} not set",
            ))
    else:
        raw.append(("Primary model API key", False, "config unavailable"))

    # ── 4. Workspace directory ───────────────────────────────────────────────
    if config is not None:
        ws_path = config.agent.workspace_path
        ws_ok = ws_path.exists() and ws_path.is_dir()
        raw.append(("Workspace directory", ws_ok, str(ws_path)))
    else:
        raw.append(("Workspace directory", False, "config unavailable"))

    # ── 5. Sessions directory ────────────────────────────────────────────────
    sessions_ok = SESSIONS_DIR.exists() and SESSIONS_DIR.is_dir()
    raw.append(("Sessions directory", sessions_ok, str(SESSIONS_DIR)))

    # ── 6. Audit directory ───────────────────────────────────────────────────
    audit_ok = AUDIT_DIR.exists() and AUDIT_DIR.is_dir()
    raw.append(("Audit directory", audit_ok, str(AUDIT_DIR)))

    # ── 7-8. Telegram (if enabled) ───────────────────────────────────────────
    if config is not None and config.channels.telegram.enabled:
        tg_cfg = config.channels.telegram
        token_env = tg_cfg.bot_token_env
        token_set = bool(os.environ.get(token_env))
        raw.append((
            f"Telegram bot token ({token_env})",
            token_set,
            "set" if token_set else f"{token_env} not set",
        ))

        try:
            import aiogram  # noqa: F401
            raw.append(("aiogram installed", True, ""))
        except ImportError:
            raw.append((
                "aiogram installed",
                False,
                "run: pip install 'munai[telegram]'",
            ))

    # ── 9. APScheduler ───────────────────────────────────────────────────────
    try:
        import apscheduler  # noqa: F401
        raw.append(("APScheduler installed", True, ""))
    except ImportError:
        raw.append(("APScheduler installed", False, "run: pip install apscheduler"))

    return [{"label": label, "ok": ok, "detail": detail} for label, ok, detail in raw]


def doctor_main(args: list[str]) -> None:
    """Print a pass/fail health report and exit 0 if all checks pass, 1 otherwise."""
    checks = run_doctor_checks()

    # ── Print report ─────────────────────────────────────────────────────────
    print("Munai Health Check")
    print("=" * 50)
    all_pass = True
    for item in checks:
        mark = "✓" if item["ok"] else "✗"
        suffix = f"  ({item['detail']})" if item["detail"] else ""
        print(f"  {mark}  {item['label']}{suffix}")
        if not item["ok"]:
            all_pass = False

    print()
    if all_pass:
        print("All checks passed.")
        sys.exit(0)
    else:
        failed = sum(1 for c in checks if not c["ok"])
        print(f"{failed} check(s) failed.")
        sys.exit(1)
