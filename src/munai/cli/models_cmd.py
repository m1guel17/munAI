"""CLI command: munai models — manage LLM provider configuration."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from .gateway_cmd import _load_dotenv
from .wizard_presets import PROVIDER_PRESETS  # noqa: F401  (single source of truth)


# ── Entry point ───────────────────────────────────────────────────────────────

def models_main(args: list[str]) -> None:
    _load_dotenv(Path.home() / ".munai" / ".env")
    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return

    subcommand = args[0]
    rest = args[1:]

    if subcommand == "list":
        _cmd_list()
    elif subcommand == "add":
        _cmd_add(rest)
    elif subcommand == "remove":
        if not rest:
            print("Usage: munai models remove <name>", file=sys.stderr)
            sys.exit(1)
        _cmd_remove(rest[0])
    elif subcommand == "set-primary":
        if not rest:
            print("Usage: munai models set-primary <name>", file=sys.stderr)
            sys.exit(1)
        _cmd_set_primary(rest[0])
    elif subcommand == "test":
        _cmd_test(rest[0] if rest else None)
    else:
        print(f"Unknown subcommand: {subcommand!r}", file=sys.stderr)
        _print_help()
        sys.exit(1)


def _print_help() -> None:
    print(
        "Usage:\n"
        "  munai models list                 List all configured providers\n"
        "  munai models add [--preset NAME]  Add a new provider (interactive)\n"
        "  munai models remove <name>        Remove a provider\n"
        "  munai models set-primary <name>   Set the primary provider\n"
        "  munai models test [name]          Test connectivity to providers\n"
        "\nAvailable presets: " + ", ".join(sorted(PROVIDER_PRESETS))
    )


# ── list ──────────────────────────────────────────────────────────────────────

def _cmd_list() -> None:
    from ..config import load_config_or_defaults
    config = load_config_or_defaults()
    models = config.models

    print(f"{'NAME':<20}  {'PRIMARY':<7}  {'FORMAT':<10}  {'MODEL':<30}  KEY")
    print("-" * 80)

    for name, provider in models.providers.items():
        is_primary = "yes" if name == models.primary else ""
        key_env = provider.api_key_env or "(none)"
        key_ok = "✓" if (not provider.api_key_env or os.environ.get(provider.api_key_env)) else "✗ missing"
        model_display = provider.model[:28] + "…" if len(provider.model) > 29 else provider.model
        print(f"{name:<20}  {is_primary:<7}  {provider.api_format.value:<10}  {model_display:<30}  {key_ok}")

    print(f"\nPrimary:  {models.primary}")
    if models.fallback:
        print(f"Fallback: {', '.join(models.fallback)}")
    if models.heartbeat:
        print(f"Heartbeat: {models.heartbeat}")


# ── add ───────────────────────────────────────────────────────────────────────

def _cmd_add(args: list[str]) -> None:
    preset_name: str | None = None
    if "--preset" in args:
        idx = args.index("--preset")
        if idx + 1 < len(args):
            preset_name = args[idx + 1]
        else:
            print("--preset requires a name", file=sys.stderr)
            sys.exit(1)

    # Choose preset
    if preset_name is None:
        print(f"Known presets: {', '.join(sorted(PROVIDER_PRESETS))}")
        preset_name = _ask("Preset (or 'custom')", default="custom")

    preset = PROVIDER_PRESETS.get(preset_name, {})

    # Provider name
    provider_name = _ask("Provider name (config key)", default=preset_name if preset_name != "custom" else "")
    if not provider_name:
        print("Provider name required.", file=sys.stderr)
        sys.exit(1)

    # Fields from preset, user can override
    base_url = _ask("Base URL", default=preset.get("base_url", "https://api.openai.com/v1"))
    api_format = _ask_choice("API format", ["openai", "anthropic"], default=preset.get("api_format", "openai"))
    model = _ask("Model", default=preset.get("model", ""))

    api_key_env_default = preset.get("api_key_env") or f"{provider_name.upper()}_API_KEY"
    api_key_raw = _ask("API key env var (or 'none')", default=api_key_env_default or "none")
    api_key_env: str | None = None if api_key_raw.lower() == "none" else api_key_raw

    supports_tools = _ask("Supports tool calling? [Y/n]", default="y").lower() not in ("n", "no")
    timeout_str = _ask("Timeout (seconds)", default=str(preset.get("timeout_seconds", 120)))
    try:
        timeout = int(timeout_str)
    except ValueError:
        timeout = 120

    if api_key_env and not os.environ.get(api_key_env):
        print(f"  Warning: {api_key_env} is not currently set.")

    # Build provider config dict
    provider_cfg: dict = {
        "name": provider_name,
        "base_url": base_url,
        "api_format": api_format,
        "model": model,
        "supports_tool_calling": supports_tools,
        "timeout_seconds": timeout,
    }
    if api_key_env:
        provider_cfg["api_key_env"] = api_key_env
    # Copy extra fields from preset
    for field in ("api_key_header", "api_key_prefix", "extra_headers", "extra_body", "models_available"):
        if field in preset:
            provider_cfg[field] = preset[field]

    # Load + mutate + write config
    config_path, raw = _load_raw_config()

    raw.setdefault("models", {}).setdefault("providers", {})[provider_name] = provider_cfg
    _write_raw_config(config_path, raw)
    print(f"Provider {provider_name!r} added.")

    # Optional: run a test
    ans = _ask("Run connectivity test now? [Y/n]", default="y")
    if ans.lower() not in ("n", "no"):
        asyncio.run(_test_one_raw(provider_cfg))


# ── remove ────────────────────────────────────────────────────────────────────

def _cmd_remove(name: str) -> None:
    config_path, raw = _load_raw_config()
    providers = raw.get("models", {}).get("providers", {})

    if name not in providers:
        print(f"Provider {name!r} not found.", file=sys.stderr)
        sys.exit(1)

    primary = raw.get("models", {}).get("primary", "")
    if name == primary:
        print(f"Cannot remove {name!r} — it is the primary provider. Set a new primary first.", file=sys.stderr)
        sys.exit(1)

    del providers[name]
    # Also remove from fallback list
    fallback = raw.get("models", {}).get("fallback", [])
    raw["models"]["fallback"] = [f for f in fallback if f != name]
    if raw["models"].get("heartbeat") == name:
        raw["models"]["heartbeat"] = None

    _write_raw_config(config_path, raw)
    print(f"Provider {name!r} removed.")


# ── set-primary ───────────────────────────────────────────────────────────────

def _cmd_set_primary(name: str) -> None:
    config_path, raw = _load_raw_config()
    providers = raw.get("models", {}).get("providers", {})

    if name not in providers:
        print(f"Provider {name!r} not found.", file=sys.stderr)
        sys.exit(1)

    raw["models"]["primary"] = name
    _write_raw_config(config_path, raw)
    print(f"Primary provider set to {name!r}.")


# ── test ──────────────────────────────────────────────────────────────────────

def _cmd_test(name: str | None) -> None:
    from ..config import load_config_or_defaults
    config = load_config_or_defaults()

    if name:
        provider = config.models.providers.get(name)
        if provider is None:
            print(f"Provider {name!r} not found.", file=sys.stderr)
            sys.exit(1)
        providers = {name: provider}
    else:
        providers = config.models.providers

    asyncio.run(_test_providers(providers))


async def _test_providers(providers: dict) -> None:
    for name, provider in providers.items():
        provider_dict = provider.model_dump() if hasattr(provider, "model_dump") else provider
        await _test_one_raw(provider_dict, name=name)


async def _test_one_raw(provider: dict, name: str | None = None) -> bool:
    """Send a minimal request to the provider and report the result."""
    import aiohttp

    label = name or provider.get("name", "?")
    base_url = provider.get("base_url", "https://api.openai.com/v1")
    api_format = provider.get("api_format", "openai")
    model = provider.get("model", "")
    api_key_env = provider.get("api_key_env")
    api_key_header = provider.get("api_key_header", "Authorization")
    api_key_prefix = provider.get("api_key_prefix", "Bearer ")
    extra_headers = provider.get("extra_headers") or {}
    timeout = provider.get("timeout_seconds", 30)

    # Build headers
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key_env:
        key = os.environ.get(api_key_env)
        if not key:
            print(f"  ✗  {label} — {api_key_env} not set (skipping)")
            return False
        headers[api_key_header] = f"{api_key_prefix}{key}"
    if api_format == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    headers.update(extra_headers)

    # Build body
    messages = [{"role": "user", "content": "Hi"}]
    if api_format == "openai":
        url = f"{base_url}/chat/completions"
        body = {"model": model, "messages": messages, "max_tokens": 5, "stream": False}
    else:
        url = f"{base_url}/messages"
        body = {"model": model, "messages": messages, "max_tokens": 5}

    t0 = time.monotonic()
    try:
        timeout_obj = aiohttp.ClientTimeout(total=min(timeout, 30))
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status in (200, 201):
                    print(f"  ✓  {label} — {model} ({elapsed}ms)")
                    return True
                else:
                    text = (await resp.text())[:200]
                    print(f"  ✗  {label} — HTTP {resp.status}: {text}")
                    return False
    except aiohttp.ClientConnectorError as exc:
        print(f"  ✗  {label} — Connection failed: {exc}")
        return False
    except asyncio.TimeoutError:
        print(f"  ✗  {label} — Timed out after {timeout}s")
        return False
    except Exception as exc:
        print(f"  ✗  {label} — Error: {exc}")
        return False


# ─── Config file I/O ──────────────────────────────────────────────────────────

def _load_raw_config() -> tuple[Path, dict]:
    from ..config import CONFIG_PATH
    if not CONFIG_PATH.exists():
        print(f"No config file found at {CONFIG_PATH}. Run 'munai onboard' first.", file=sys.stderr)
        sys.exit(1)
    import json5
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return CONFIG_PATH, json5.load(f)


def _write_raw_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ─── Interactive helpers ───────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    try:
        ans = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return ans if ans else default


def _ask_choice(prompt: str, choices: list[str], default: str) -> str:
    choices_str = "/".join(c.upper() if c == default else c for c in choices)
    while True:
        ans = _ask(f"{prompt} ({choices_str})", default=default).lower()
        if ans in choices:
            return ans
        print(f"  Please choose one of: {', '.join(choices)}")
