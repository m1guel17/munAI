"""Provider resolution, request building, and failover logic.

Public API (importable by external consumers such as Mission Control):

    from munai.agent.model_resolver import ModelResolver
"""
from __future__ import annotations

__all__ = ["ModelResolver"]

import logging
import time
from typing import TYPE_CHECKING, Any

from ..config import ApiFormat, ModelsConfig, ProviderConfig

if TYPE_CHECKING:
    import openai

log = logging.getLogger(__name__)

# Exponential cooldown: 60 → 120 → 240 → 480 seconds (max)
_COOLDOWN_BASE = 60
_COOLDOWN_MAX = 480

# Anthropic API version header value
_ANTHROPIC_VERSION = "2023-06-01"


class ModelResolver:
    """Resolves providers and builds OpenAI SDK clients.

    Usage:
    - ``get_client(index)`` → ``(AsyncOpenAI, model_id, ProviderConfig)``
    - ``build_request()``   → raw (url, headers, body) for aiohttp (used by models_cmd).

    Failover state (cooldowns) is maintained per-instance.
    """

    def __init__(self, config: ModelsConfig) -> None:
        self._config = config
        # name → (cooldown_until: float, retry_count: int)
        self._cooldowns: dict[str, tuple[float, int]] = {}

    # ─── Provider resolution ──────────────────────────────────────────────────

    def resolve_provider(self, role: str = "primary") -> ProviderConfig:
        """Return the ProviderConfig for the given role ("primary" or "heartbeat")."""
        if role == "heartbeat":
            name = self._config.heartbeat or self._config.primary
        else:
            name = self._config.primary
        return self._config.providers[name]

    def _provider_at_index(self, index: int) -> ProviderConfig:
        """Return provider at failover index (0=primary, 1+=fallback[index-1])."""
        names = [self._config.primary] + list(self._config.fallback)
        if index >= len(names):
            raise RuntimeError(
                f"No model at failover index {index}. "
                f"Only {self.model_count()} model(s) configured."
            )
        return self._config.providers[names[index]]

    def _provider_sequence(self) -> list[ProviderConfig]:
        """All providers in failover order, excluding cooled-down ones."""
        names = [self._config.primary] + list(self._config.fallback)
        return [
            self._config.providers[n]
            for n in names
            if n in self._config.providers and not self._is_cooled_down(n)
        ]

    # ─── OpenAI SDK client construction ──────────────────────────────────────

    def get_client(self, index: int = 0) -> "tuple[openai.AsyncOpenAI, str, ProviderConfig]":
        """Return (AsyncOpenAI client, model_id, ProviderConfig) at failover index.

        Raises:
            RuntimeError: if index is out of range, or the API key is missing.
        """
        from .. import llm_client

        provider = self._provider_at_index(index)
        key = provider.resolve_api_key()
        if key is None and provider.api_key_env is not None:
            raise RuntimeError(
                f"API key environment variable {provider.api_key_env!r} not set for "
                f"provider {provider.name!r}. "
                f"Set it with: export {provider.api_key_env}=your_key_here"
            )

        # Honour LLM_* env var overrides if fully set
        override = llm_client.get_env_override()
        if override is not None:
            base_url, api_key, model = override
            import openai
            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=openai.Timeout(connect=10.0, read=30.0),
                max_retries=0,
            )
            return client, model, provider

        client = llm_client.build_client(provider)
        return client, provider.model, provider

    def get_heartbeat_client(self) -> "tuple[openai.AsyncOpenAI, str, ProviderConfig]":
        """Return the heartbeat (client, model, provider), falling back to primary."""
        from .. import llm_client

        provider = self.resolve_provider("heartbeat")
        client = llm_client.build_client(provider)
        return client, provider.model, provider

    def model_count(self) -> int:
        """Total number of configured models (primary + all fallbacks)."""
        return 1 + len(self._config.fallback)

    # ─── Request building (used by models_cmd for raw connectivity tests) ─────

    def build_request(
        self,
        provider: ProviderConfig,
        messages: list,
        tools: list | None = None,
    ) -> tuple[str, dict, dict]:
        """Build ``(url, headers, body)`` ready for ``aiohttp.ClientSession.post()``.

        Args:
            provider: The provider configuration.
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            tools: Optional tool definitions (omitted if None or provider doesn't support them).

        Returns:
            Tuple of (url, headers, body).
        """
        # ── Auth header ──────────────────────────────────────────────────────
        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = provider.resolve_api_key()
        if key is not None:
            headers[provider.api_key_header] = f"{provider.api_key_prefix}{key}"
        elif provider.api_key_env is not None:
            raise RuntimeError(
                f"Environment variable {provider.api_key_env!r} not set for provider "
                f"{provider.name!r}. Set it with: export {provider.api_key_env}=your_key_here"
            )
        # Anthropic requires its version header
        if provider.api_format == ApiFormat.ANTHROPIC:
            headers["anthropic-version"] = _ANTHROPIC_VERSION
        # User-defined extra_headers can override any of the above
        headers.update(provider.extra_headers)

        # ── Build body ───────────────────────────────────────────────────────
        if provider.api_format == ApiFormat.OPENAI:
            url = f"{provider.base_url}/chat/completions"
            body: dict = {
                "model": provider.model,
                "messages": messages,
                "stream": True,
            }
            if tools and provider.supports_tool_calling:
                body["tools"] = tools
        else:  # ANTHROPIC
            url = f"{provider.base_url}/messages"
            body = {
                "model": provider.model,
                "messages": messages,
                "max_tokens": 8096,
                "stream": True,
            }
            if tools and provider.supports_tool_calling:
                body["tools"] = tools

        # Shallow-merge extra_body (top-level keys only; must not overwrite messages/tools)
        body.update(provider.extra_body)

        return url, headers, body

    # ─── Cooldown management ──────────────────────────────────────────────────

    def _set_cooldown(self, name: str) -> None:
        """Apply exponential backoff cooldown to a provider."""
        count = self._cooldowns.get(name, (0, 0))[1]
        backoff = min(_COOLDOWN_BASE * (2 ** count), _COOLDOWN_MAX)
        self._cooldowns[name] = (time.monotonic() + backoff, count + 1)
        log.info("Provider %r on cooldown for %ds (attempt %d)", name, backoff, count + 1)

    def _is_cooled_down(self, name: str) -> bool:
        """Return True if the provider is currently in cooldown."""
        if name not in self._cooldowns:
            return False
        until, _ = self._cooldowns[name]
        return time.monotonic() < until
