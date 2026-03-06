# Configuration Reference

All configuration lives in `~/.munai/munai.json` (JSON5 format — comments and trailing commas are allowed). Use `munai config get <key>` and `munai config set <key> <value>` for individual values, or edit the file directly.

**Precedence:** Environment variables > config file > built-in defaults.

---

## Models

```json5
{
  models: {
    primary: "anthropic",        // Name of the primary provider (must match a key in providers)
    fallback: ["groq", "ollama"], // Ordered fallback list
    heartbeat: "groq",           // Provider for heartbeat runs (null = use primary)
    providers: { ... },
  },
}
```

### Provider configuration

Each provider is an object in `models.providers`:

```json5
{
  name: "groq",                                // Human-readable name (used in logs)
  base_url: "https://api.groq.com/openai/v1", // Full base URL including /v1 path
  api_format: "openai",                        // "openai" or "anthropic"
  api_key_env: "GROQ_API_KEY",                 // Env var name containing the API key
  api_key_header: "Authorization",             // HTTP header for the key (default: Authorization)
  api_key_prefix: "Bearer ",                   // Prefix for the key value (default: "Bearer ")
  model: "llama-3.3-70b-versatile",            // Default model ID
  models_available: [],                        // Optional: list of valid model IDs
  max_retries: 2,                              // Retries on 429/5xx before failover
  timeout_seconds: 120,                        // Request timeout
  supports_tool_calling: true,                 // False: falls back to prompt-based tools
  supports_streaming: true,                    // False: waits for full response
  extra_headers: {},                           // Merged into every request header
  extra_body: {},                              // Merged into every request body (shallow)
}
```

**API key security:** Keys are never stored in the config file. `api_key_env` is the name of an environment variable. The actual key is read from `os.environ` at call time.

**Failover:** On 429 (rate limit) or 5xx, the runtime cools down the current provider (exponential backoff: 60s → 120s → 240s → 480s) and tries the next in the fallback list. On 401/403, the provider is marked unhealthy and skipped.

### Adding providers

```bash
munai models add --preset groq     # From a known preset
munai models add                   # Interactive (any provider)
munai models list                  # Show all providers + API key status
munai models test                  # Test connectivity to all providers
munai models set-primary groq      # Change primary provider
munai models remove deepseek       # Remove a provider
```

**Known presets:** anthropic, openai, groq, together, mistral, deepseek, openrouter, xai, fireworks, cerebras, perplexity, ollama, vllm, lm-studio

---

## Gateway

```json5
{
  gateway: {
    bind: "127.0.0.1", // Bind address. "0.0.0.0" for LAN access (requires token)
    port: 18700,       // WebSocket + HTTP port
    token_env: "MUNAI_GATEWAY_TOKEN", // Env var for gateway auth token (null = no auth)
  },
}
```

The gateway **only listens on loopback by default**. If you change `bind` to anything other than `127.0.0.1`, a `token_env` must be set or the config is rejected at startup.

---

## Agent

```json5
{
  agent: {
    workspace: "~/.munai/workspace",   // Path to workspace directory
    max_tool_iterations: 25,           // Max tool calls per turn before hard stop
    max_turn_duration_seconds: 300,    // Max wall-clock time per turn (5 minutes)
    bootstrap_max_chars: 20000,        // Per-file truncation limit for workspace files
    bootstrap_total_max_chars: 150000, // Total cap on all bootstrap file content
  },
}
```

---

## Channels

### WebChat

WebChat is always enabled when the gateway is running. No additional configuration is required.

### Telegram

```json5
{
  channels: {
    telegram: {
      enabled: false,                       // Set to true to activate
      bot_token_env: "TELEGRAM_BOT_TOKEN",  // Env var containing the bot token
      allow_from: [],                       // Telegram user IDs that can interact
      dm_policy: "pairing",                 // "pairing" | "open" | "closed"
    },
  },
}
```

`dm_policy`:
- `"pairing"` — Unknown senders receive a 6-character pairing code. Approve with `munai pairing approve telegram <code>`.
- `"open"` — Anyone can message the bot (not recommended for production).
- `"closed"` — Only `allow_from` users are accepted. Unknown senders are silently ignored.

---

## Heartbeat

```json5
{
  heartbeat: {
    enabled: true,
    interval_minutes: 30,
    ack_keyword: "HEARTBEAT_OK", // Response containing this keyword is silently suppressed
  },
}
```

The heartbeat runs the agent on a schedule using the content of `~/.munai/workspace/HEARTBEAT.md` as the prompt. If the file is empty or contains only comments, the heartbeat tick is skipped (no API call is made).

---

## Tools

```json5
{
  tools: {
    allow: ["file_read", "file_write", "file_edit", "shell_exec"], // Enabled tools
    deny: [],                    // Explicitly blocked tools (takes priority over allow)
    workspace_only: true,        // Restrict file tools to the workspace directory
    shell_approval_mode: "always", // "always" | "once" | "never"
    max_output_chars: 50000,     // Tool output is truncated to this length
    redact_patterns: [           // Regex patterns: matches are replaced with [REDACTED]
      "(?i)(api[_-]?key|secret|password|token)\\s*[:=]\\s*\\S+"
    ],
  },
}
```

`shell_approval_mode`:
- `"always"` (default) — Every `shell_exec` call pauses and asks for user approval via the WebChat UI.
- `"once"` — Ask once per session; auto-approve all subsequent commands.
- `"never"` — Auto-approve all commands. Use only in trusted environments.

---

## Audit

```json5
{
  audit: {
    enabled: true,
    retention_days: 90,          // Audit files older than this are deleted on startup
    log_llm_prompts: false,      // Log full prompts (warning: very large!)
    log_tool_output: true,       // Include tool output in audit entries
    redact_in_audit: true,       // Apply redact_patterns to audit log entries
  },
}
```

Audit logs are written to `~/.munai/audit/<YYYY-MM-DD>.jsonl` (one file per day, one JSON object per line). They are human-readable and grep-able.

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `MUNAI_GATEWAY_TOKEN` | Gateway auth token (required when `bind` is non-loopback) |
| `ANTHROPIC_API_KEY` | API key for Anthropic |
| `OPENAI_API_KEY` | API key for OpenAI |
| `GROQ_API_KEY` | API key for Groq |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `MUNAI_LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

API keys for all providers follow the pattern `<PROVIDER>_API_KEY`. You can also add them to `~/.munai/.env` (read at gateway startup) instead of setting them in your shell environment.
