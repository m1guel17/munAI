"""CLI command: munai gateway — start the Gateway process."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path


def _load_dotenv(env_file: Path) -> None:
    """Load KEY=VALUE lines from env_file into os.environ (existing vars are NOT overwritten)."""
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def gateway_main(args: list[str]) -> None:
    """Entry point for the 'munai gateway' command."""
    _configure_logging()
    _load_dotenv(Path.home() / ".munai" / ".env")

    from ..config import load_config_or_defaults, CONFIG_PATH

    config_path = CONFIG_PATH
    # Allow --config <path> override
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            config_path = Path(args[i + 1])

    try:
        config = load_config_or_defaults(config_path)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run(config))


async def _run(config: object) -> None:
    from ..config import Config
    from ..gateway.server import GatewayServer

    assert isinstance(config, Config)
    server = GatewayServer(config)

    print(
        f"Starting Munai gateway on http://{config.gateway.bind}:{config.gateway.port}"
    )

    await server.start()

    try:
        # Run until interrupted
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nShutting down...")
    finally:
        await server.stop()


def _configure_logging() -> None:
    level_name = os.environ.get("MUNAI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Quiet down noisy third-party loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("pydantic_ai").setLevel(logging.WARNING)
