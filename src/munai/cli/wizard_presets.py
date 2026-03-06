"""Provider presets shared by the onboarding wizard and the models CLI."""
from __future__ import annotations

# ── Known provider presets ────────────────────────────────────────────────────
# Each entry is a partial ProviderConfig dict (missing: name, which is the key).

PROVIDER_PRESETS: dict[str, dict] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o",
        "models_available": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "api_format": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "api_key_header": "x-api-key",
        "api_key_prefix": "",
        "model": "claude-sonnet-4-6",
        "models_available": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "model": "meta-llama/Llama-3-70b-chat-hf",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "model": "mistral-large-latest",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1", #
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "anthropic/claude-sonnet-4-5",
        "extra_headers": {"HTTP-Referer": "https://munai.local", "X-Title": "Munai"},
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "model": "grok-3-mini",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key_env": "FIREWORKS_API_KEY",
        "model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        "model": "llama-3.3-70b",
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "model": "sonar-pro",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_env": None,
        "model": "qwen3:8b",
        "timeout_seconds": 300,
        "supports_tool_calling": False,
    },
    "vllm": {
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key_env": None,
        "model": "default",
        "timeout_seconds": 300,
    },
    "lm-studio": {
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key_env": None,
        "model": "default",
        "timeout_seconds": 300,
    },
}

# ── Wizard provider list ───────────────────────────────────────────────────────
# Ordered list of provider names shown in the onboarding wizard picker.
# "custom" and "skip" are special: not in PROVIDER_PRESETS.

WIZARD_PROVIDERS = [
    "anthropic",
    "openai",
    "groq",
    "deepseek",
    "mistral",
    "openrouter",
    "ollama",
    "custom",
    "skip",
]

# Human-readable labels for the wizard picker.
WIZARD_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic (recommended)",
    "openai": "OpenAI",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "openrouter": "OpenRouter",
    "ollama": "Ollama (local, free)",
    "custom": "Other OpenAI-compatible provider",
    "skip": "Skip for now",
}
