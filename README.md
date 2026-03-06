# munAI — Personal AI Assistant

**Your own AI assistant. Self-hosted. Always on. Your data, your hardware, your rules.**
<div align="center">
<img src="munai_logo.png" style="width:500%; height:auto;">

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/downloads/)
</div>

---

munAI is a self-hosted personal AI assistant that runs as a persistent background process on your own hardware. You interact with it through the messaging platforms you already use — Telegram, a browser-based WebChat, or the CLI. It can reason, take actions on your system, remember context across sessions, and act proactively on a schedule.

This is not a chatbot. It's an agent orchestration platform with a messaging interface.

## Why munAI?

- **Local-first.** All data — memory, sessions, config, audit logs — lives on your filesystem as human-readable files. No external databases. Git-backable. Grep-able.
- **Secure by default.** Shell commands require approval. File access is restricted to the workspace. Every action is logged. The hardened path is the default path.
- **Model-agnostic.** Works with Anthropic, OpenAI, Groq, Mistral, DeepSeek, OpenRouter, Ollama, vLLM, LM Studio, and any OpenAI-compatible provider. Swap models without rewriting anything.
- **Auditable.** Every tool call, every LLM request, every state mutation is logged with enough context to reconstruct what happened and why.
- **Extensible.** Skills are Markdown files that teach the agent new capabilities at runtime. Drop a file, agent learns a new trick. No compilation, no restart.

## Quick Start

```bash
pip install munai

munai onboard
```

The onboarding wizard walks you through model setup, channel configuration, and workspace initialization in under 10 minutes.

```bash
# Start the gateway
munai gateway

# Or install as a background service
munai onboard --install-daemon
```

Once running, open `http://127.0.0.1:18700` in your browser to chat via WebChat, or message your Telegram bot.

## How It Works

```
Telegram / WebChat / CLI
         │
         ▼
┌──────────────────────────┐
│        Gateway           │
│     (control plane)      │
│   ws://127.0.0.1:18700   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│    Agent Runtime         │
│                          │
│  Context Assembly        │
│  → LLM Inference         │
│  → Tool Execution        │
│  → Stream Response       │
│  → Persist to Session    │
└──────────────────────────┘
```

The **Gateway** is a single async Python process that handles all message routing, authentication, session management, and channel connections. It never reasons — it only routes.

The **Agent Runtime** runs the agentic loop: assemble context from workspace files and session history → call the LLM → execute any tool calls the model requests → stream the response → persist the full turn to a JSONL transcript.

Your agent's identity, personality, and memory live as plain Markdown files in the workspace:

| File | Purpose |
|---|---|
| `AGENTS.md` | Operating instructions — rules, priorities, boundaries |
| `SOUL.md` | Persona — voice, tone, personality |
| `USER.md` | Your profile — name, preferences, work context |
| `TOOLS.md` | Tool usage guidance and conventions |
| `HEARTBEAT.md` | Proactive task checklist (runs on a timer) |
| `MEMORY.md` | Long-term memory (agent-managed) |
| `skills/` | Skill files that teach the agent new capabilities |

All of these are readable, editable, and version-controllable with Git.

## Features

### Channels
- **WebChat** — Browser-based chat UI served by the gateway
- **Telegram** — Connect a Telegram bot in minutes
- More channels planned (Discord, Slack, WhatsApp)

### Tools
- **File operations** — Read, write, edit files within the workspace
- **Shell execution** — Run commands with configurable approval policy
- **Skills** — Markdown-based instructions that teach the agent new workflows

### Security
- Shell commands require human approval by default
- File tools restricted to workspace directory (no path traversal)
- All tool executions logged to an append-only audit trail
- Secret redaction in logs and tool output
- DM pairing for messaging channels (unknown senders must pair before interacting)

### Proactive Behavior
- Configurable heartbeat (default: every 30 minutes)
- Agent reads `HEARTBEAT.md`, decides if action is needed
- Can send you messages, check on tasks, monitor things — even when you're not talking to it

### Multi-Provider Support
Works with any LLM provider. Configure a primary and fallback chain:

| Provider | Type |
|---|---|
| Anthropic | Native API |
| OpenAI | OpenAI-compatible |
| Groq | OpenAI-compatible |
| DeepSeek | OpenAI-compatible |
| Mistral | OpenAI-compatible |
| OpenRouter | OpenAI-compatible (aggregator) |
| Ollama | Local, free |
| vLLM | Local |
| LM Studio | Local |
| Any OpenAI-compatible endpoint | Custom URL + API key |

Automatic failover with exponential backoff when a provider goes down.

### Audit Trail
Every action the agent takes is logged:

```jsonl
{"timestamp":"2026-03-05T10:42:03Z","event_type":"tool.call","detail":{"tool":"shell_exec","params":["ls","-la"]}}
{"timestamp":"2026-03-05T10:42:03Z","event_type":"tool.result","detail":{"tool":"shell_exec","success":true,"duration_ms":12}}
{"timestamp":"2026-03-05T10:42:04Z","event_type":"agent.model_call","detail":{"provider":"anthropic","tokens_in":1420,"tokens_out":85,"cost_usd":0.004}}
```

Searchable via CLI (`munai audit search`) and the web UI audit viewer.

## Web UI

The gateway serves a built-in admin dashboard at `http://127.0.0.1:18700/`:

- **Chat** — Real-time streaming conversation with tool call visualization
- **Sessions** — List, switch, reset, compact, export sessions
- **Health** — Gateway status, model provider reachability, host metrics
- **Audit Log** — Searchable, filterable audit trail with live tail mode
- **Usage** — Token counts and cost tracking per session, per model, per day
- **Tools** — Catalog of available tools with approval queue
- **Skills** — Browse, enable, install skills
- **Config** — Form-based configuration editor

Vanilla HTML/CSS/JS. No build step. No framework. Dark mode by default.

## CLI

```bash
munai onboard                          # Interactive setup wizard
munai gateway                          # Start the gateway
munai doctor                           # Check config + connectivity
munai status                           # Gateway health + active sessions

munai agent --message "hello"          # One-shot message
munai sessions list                    # List sessions
munai sessions reset <id>              # Reset a session

munai models list                      # Show configured providers
munai models add --preset groq         # Add a provider from preset
munai models test                      # Test all providers

munai audit search --type tool.call    # Search audit log
munai audit tail                       # Live-stream audit events

munai skills list                      # List installed skills
munai pairing approve telegram ABC123  # Approve a device pairing
```

## Configuration

Single config file at `~/.munai/munai.json` (JSON5 — comments and trailing commas allowed):

```json5
{
  models: {
    primary: "anthropic",
    fallback: ["groq", "ollama"],
    providers: {
      anthropic: {
        name: "anthropic",
        base_url: "https://api.anthropic.com/v1",
        api_format: "anthropic",
        api_key_env: "ANTHROPIC_API_KEY",  // never stored as plaintext
        model: "claude-sonnet-4-5-20250929",
      },
      groq: {
        name: "groq",
        base_url: "https://api.groq.com/openai/v1",
        api_key_env: "GROQ_API_KEY",
        model: "llama-3.3-70b-versatile",
      },
      ollama: {
        name: "ollama",
        base_url: "http://127.0.0.1:11434/v1",
        api_key_env: null,  // local, no auth
        model: "qwen3:8b",
      },
    },
  },
  tools: {
    shell_approval_mode: "always",  // every shell command asks for permission
    workspace_only: true,            // file tools can't escape the workspace
  },
}
```

API keys are referenced by environment variable name — never stored as plaintext in config.

## Architecture

munAI follows a hub-and-spoke architecture inspired by [OpenClaw](https://github.com/openclaw/openclaw), rebuilt from scratch in Python with security and auditability as first-class concerns.

```
~/.munai/
├── munai.json              # Configuration
├── .env                    # API keys (chmod 600)
├── workspace/
│   ├── AGENTS.md           # Agent operating instructions
│   ├── SOUL.md             # Agent persona
│   ├── USER.md             # Your profile
│   ├── IDENTITY.md         # Agent identity
│   ├── TOOLS.md            # Tool usage guidance
│   ├── HEARTBEAT.md        # Proactive checklist
│   ├── MEMORY.md           # Long-term memory
│   ├── memory/             # Daily session notes
│   └── skills/             # Skill markdown files
├── sessions/               # JSONL transcripts
├── audit/                  # JSONL audit trail
└── auth/                   # Device pairing + allowlists
```

Everything is files. No database. No Redis. No Docker (unless you want sandboxing). Inspect with any text editor. Back up with Git.

## Development

```bash
git clone https://github.com/m1guel17/munAI.git
cd munAI

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Start in dev mode
munai gateway --verbose
```

### Project Structure

```
src/munai/
├── main.py                 # CLI entry point
├── config.py               # Config loading + validation
├── gateway/                # WebSocket + HTTP server
├── channels/               # Channel adapters (Telegram, WebChat)
├── agent/                  # Agentic loop, context assembly, model resolution
├── tools/                  # File read/write/edit, shell exec, policy enforcement
├── audit/                  # Append-only JSONL audit system
├── skills/                 # Skill loader + manifest builder
├── workspace/              # Bootstrap file creation
└── cli/                    # CLI commands (onboard, doctor, sessions, etc.)
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

- **Bug reports:** Open an issue with reproduction steps.
- **Feature requests:** Open an issue describing the use case.
- **Code:** Fork, branch, PR. Tests required for new features.
- **Skills:** Share your skills! Open a PR adding your `SKILL.md` to the community skills directory.

## Security

If you discover a security vulnerability, please report it privately via [GitHub Security Advisories](https://github.com/m1guel17/munAI/security/advisories/new) rather than opening a public issue.

munAI runs with access to your filesystem and can execute shell commands. Treat it with the same caution you would give to any software with system access. See [SECURITY.md](https://github.com/m1guel17/munAI/tree/main/docs/security.md) for the full security model.

## Acknowledgments

munAI's architecture is inspired by [OpenClaw](https://github.com/openclaw/openclaw) by Peter Steinberger and the OpenClaw community. The gateway + agent runtime separation, workspace-as-filesystem design, and skill system are direct descendants of patterns pioneered in that project. munAI is a from-scratch Python implementation with a focus on security-by-default and auditability.

## License

[MIT](LICENSE) — Use it however you want.