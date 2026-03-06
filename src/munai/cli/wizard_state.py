"""WizardState: accumulated state across onboarding wizard steps."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WizardState:
    """Accumulated state built up as wizard steps run."""

    # Flow control
    flow: str = "quickstart"           # "quickstart" | "advanced"
    reset: bool = False                # --reset flag

    # Provider / model
    provider_name: str | None = None
    model: str | None = None

    # Channels
    channels: list[str] = field(default_factory=lambda: ["webchat"])
    telegram_token_env: str | None = None   # env var name holding the bot token
    telegram_dm_policy: str = "pairing"     # "pairing" | "open" | "closed"
    telegram_allow_from: list[str] = field(default_factory=list)

    # Gateway
    gateway_port: int = 18700
    gateway_bind: str = "127.0.0.1"
    gateway_token: str | None = None        # auto-generated or user-supplied

    # Workspace
    workspace_path: str = "~/.munai/workspace"

    # Env vars to write to ~/.munai/.env
    # Maps env_var_name → actual_secret_value
    env_vars: dict[str, str] = field(default_factory=dict)

    # Security / tools
    shell_approval_mode: str = "always"    # "always" | "once" | "never"
    workspace_only: bool = True

    # Heartbeat
    heartbeat_enabled: bool = True
    heartbeat_interval: int = 30           # minutes

    # Audit
    audit_enabled: bool = True
    audit_retention: int = 90              # days

    # Gateway startup choice
    start_gateway: str = "no"             # "foreground" | "daemon" | "no"

    # State flags
    existing_config: bool = False
    skip_channels: bool = False

    # Validation
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # The raw config dict being assembled
    config: dict = field(default_factory=dict)
