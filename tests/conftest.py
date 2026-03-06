"""Shared pytest fixtures for munAI tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from munai.config import (
    AgentConfig,
    ApiFormat,
    AuditConfig,
    ChannelsConfig,
    Config,
    GatewayConfig,
    HeartbeatConfig,
    ModelsConfig,
    ProviderConfig,
    ToolsConfig,
)


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A temporary workspace directory with no files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def minimal_config(tmp_workspace: Path) -> Config:
    """A minimal Config with Anthropic as primary provider."""
    return Config(
        models=ModelsConfig(
            primary="anthropic",
            providers={
                "anthropic": ProviderConfig(
                    name="anthropic",
                    base_url="https://api.anthropic.com/v1",
                    api_format=ApiFormat.ANTHROPIC,
                    api_key_env="ANTHROPIC_API_KEY",
                    api_key_header="x-api-key",
                    api_key_prefix="",
                    model="claude-sonnet-4-6",
                )
            },
        ),
        gateway=GatewayConfig(bind="127.0.0.1", port=18700, token_env=None),
        agent=AgentConfig(workspace=str(tmp_workspace)),
        channels=ChannelsConfig(),
        heartbeat=HeartbeatConfig(enabled=False),
        tools=ToolsConfig(),
        audit=AuditConfig(enabled=False),
    )
