"""Configuration loading and validation for munAI.

Public API (importable by external consumers such as Mission Control):

    from munai.config import load_config, MunaiConfig, ModelsConfig, ProviderConfig
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Union

import json5
from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ApiFormat",
    "ProviderConfig",
    "ModelsConfig",
    "GatewayConfig",
    "AgentConfig",
    "WebchatChannelConfig",
    "TelegramChannelConfig",
    "ChannelsConfig",
    "HeartbeatConfig",
    "ToolsConfig",
    "AuditConfig",
    "Config",
    "MunaiConfig",
    "load_config",
    "load_config_or_defaults",
    "MUNAI_DIR",
    "CONFIG_PATH",
]

MUNAI_DIR = Path.home() / ".munai"
CONFIG_PATH = MUNAI_DIR / "munai.json"


class ApiFormat(str, Enum):
    """Wire format for LLM API requests.

    - openai: POST /chat/completions (OpenAI-compatible, ~90% of providers).
    - anthropic: POST /messages (Anthropic Messages API).
    """
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    # Identity
    name: str = Field(description="Human-readable name, used as key in providers dict.")

    # Connection
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the provider's API. No trailing slash.",
    )
    api_format: ApiFormat = Field(
        default=ApiFormat.OPENAI,
        description="Wire format: 'openai' for OpenAI-compatible, 'anthropic' for Anthropic.",
    )

    # Authentication
    api_key_env: Optional[str] = Field(
        default=None,
        description="Env var name containing the API key. Null for local runtimes.",
    )
    api_key_header: str = Field(
        default="Authorization",
        description="HTTP header name for auth. Anthropic uses 'x-api-key'.",
    )
    api_key_prefix: str = Field(
        default="Bearer ",
        description="Prefix prepended to key in auth header. Empty for raw-key providers.",
    )

    # Models
    model: str = Field(description="Default model ID for this provider.")
    models_available: list[str] = Field(
        default_factory=list,
        description="Optional list of valid model IDs for validation/UI.",
    )

    # Behavior
    max_retries: int = Field(default=2, description="Max retries on transient errors.")
    timeout_seconds: int = Field(default=120, description="Request timeout in seconds.")
    supports_tool_calling: bool = Field(
        default=True,
        description="Whether this provider supports native function/tool calling.",
    )
    supports_streaming: bool = Field(
        default=True,
        description="Whether this provider supports SSE streaming responses.",
    )

    # Extensions
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers included in every request.",
    )
    extra_body: dict = Field(
        default_factory=dict,
        description="Additional fields shallow-merged into every request body.",
    )

    def resolve_api_key(self) -> str | None:
        """Look up API key from environment at runtime; never store it."""
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


class ModelsConfig(BaseModel):
    """Top-level model configuration: provider registry + failover order."""

    primary: str = Field(description="Name of the primary provider (key in `providers`).")
    fallback: list[str] = Field(
        default_factory=list,
        description="Ordered fallback provider names tried when primary fails.",
    )
    heartbeat: Optional[str] = Field(
        default=None,
        description="Provider name for heartbeat runs (cheaper model). Defaults to primary.",
    )
    providers: dict[str, ProviderConfig] = Field(
        description="Registry of all configured providers, keyed by name.",
    )

    @model_validator(mode="after")
    def validate_provider_refs(self) -> "ModelsConfig":
        known = set(self.providers)
        if self.primary not in known:
            raise ValueError(
                f"Primary provider {self.primary!r} not in providers. "
                f"Available: {sorted(known)}"
            )
        for name in self.fallback:
            if name not in known:
                raise ValueError(
                    f"Fallback provider {name!r} not in providers. "
                    f"Available: {sorted(known)}"
                )
        if self.heartbeat and self.heartbeat not in known:
            raise ValueError(
                f"Heartbeat provider {self.heartbeat!r} not in providers. "
                f"Available: {sorted(known)}"
            )
        return self


class GatewayConfig(BaseModel):
    bind: str = "127.0.0.1"
    port: int = 18700
    token_env: str | None = "MUNAI_GATEWAY_TOKEN"

    def resolve_token(self) -> str | None:
        """Look up gateway token from environment. Returns None if not required."""
        if self.token_env is None:
            return None
        return os.environ.get(self.token_env)


class AgentConfig(BaseModel):
    workspace: str = "~/.munai/workspace"
    max_tool_iterations: int = 25
    max_turn_duration_seconds: int = 300
    bootstrap_max_chars: int = 20_000
    bootstrap_total_max_chars: int = 150_000

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser().resolve()


class WebchatChannelConfig(BaseModel):
    enabled: bool = True


class TelegramChannelConfig(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    allow_from: list[str] = Field(default_factory=list)
    dm_policy: Literal["pairing", "open", "closed"] = "pairing"

    def resolve_bot_token(self) -> str | None:
        return os.environ.get(self.bot_token_env)


class ChannelsConfig(BaseModel):
    webchat: WebchatChannelConfig = Field(default_factory=WebchatChannelConfig)
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)


class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 30
    ack_keyword: str = "HEARTBEAT_OK"


class ToolsConfig(BaseModel):
    allow: list[str] = Field(
        default_factory=lambda: ["file_read", "file_write", "file_edit", "shell_exec"]
    )
    deny: list[str] = Field(default_factory=list)
    workspace_only: bool = True
    shell_approval_mode: Literal["always", "once", "never"] = "always"
    max_output_chars: int = 50_000
    redact_patterns: list[str] = Field(
        default_factory=lambda: [
            r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"
        ]
    )


class AuditConfig(BaseModel):
    enabled: bool = True
    retention_days: int = 90
    log_llm_prompts: bool = False
    log_tool_output: bool = True
    redact_in_audit: bool = True


class Config(BaseModel):
    models: ModelsConfig
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @model_validator(mode="after")
    def require_token_for_non_loopback(self) -> "Config":
        if self.gateway.bind != "127.0.0.1":
            token = self.gateway.resolve_token()
            if not token:
                raise ValueError(
                    "Gateway bound to non-loopback address but no token is set. "
                    "Configure token_env in [gateway] and set that environment variable."
                )
        return self


def _default_anthropic_provider() -> ProviderConfig:
    return ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_format=ApiFormat.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_header="x-api-key",
        api_key_prefix="",
        model="claude-sonnet-4-6",
    )


#: Alias for ``Config`` — use this name when importing from external code.
MunaiConfig = Config


def load_config(path: Union[str, Path] = CONFIG_PATH) -> Config:
    """Load and validate config from a JSON5 file.

    Args:
        path: Path to the config file (string or :class:`pathlib.Path`).
              Tilde expansion is applied automatically.

    Raises:
        FileNotFoundError: if the config file does not exist.
        pydantic.ValidationError: if the config is invalid.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found at {path}. Run 'munai onboard' to create it."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = json5.load(f)
    return Config.model_validate(raw)


def load_config_or_defaults(path: Union[str, Path] = CONFIG_PATH) -> Config:
    """Load config or return a sensible default (for dev/test).

    Uses ANTHROPIC_API_KEY if set, otherwise leaves the api_key_env pointing
    at the env var name so callers get a clear error at call time.
    """
    try:
        return load_config(path)
    except FileNotFoundError:
        provider = _default_anthropic_provider()
        return Config(
            models=ModelsConfig(
                primary="anthropic",
                providers={"anthropic": provider},
            )
        )
