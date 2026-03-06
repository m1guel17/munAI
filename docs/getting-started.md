# Getting Started

This guide walks you through installing munAI, running the onboarding wizard, and having your first conversation.

## Requirements

- Python 3.12 or later
- An API key for at least one LLM provider (Anthropic, OpenAI, Groq, etc.) — or a locally-running Ollama instance for a fully offline setup

## Installation

```bash
pip install munai
```

To include the optional Telegram channel support:

```bash
pip install "munai[telegram]"
```

## First Run: `munai onboard`

The onboarding wizard configures everything in one guided flow:

```bash
munai onboard
```

The wizard will:

1. Check your Python version and create `~/.munai/`
2. Show a security warning (read it — munAI can run shell commands)
3. Ask which LLM provider to use and prompt for your API key
4. Test connectivity to your chosen provider
5. Optionally connect a Telegram bot
6. Create your workspace files (`AGENTS.md`, `SOUL.md`, `USER.md`, etc.)
7. Write `~/.munai/munai.json`
8. Optionally start the gateway or install it as a system service

### Non-interactive mode

For scripted setups (CI, containers, dotfiles):

```bash
munai onboard --flow quickstart \
  --provider anthropic \
  --model claude-sonnet-4-5-20250929 \
  --api-key-env ANTHROPIC_API_KEY
```

## Starting the Gateway

If you did not start it during onboarding:

```bash
munai gateway
```

The gateway listens on `ws://127.0.0.1:18700` by default. Open `http://127.0.0.1:18700/` in a browser to access the WebChat UI.

To run as a background service:

```bash
munai gateway --daemon
```

## Your First Conversation

Open `http://127.0.0.1:18700/` and type a message. The assistant will respond using the model you configured.

Try:

- `Hello! Who are you?` — the assistant introduces itself using `IDENTITY.md`
- `Create a file called hello.txt with "Hello, world!" in it` — exercises the file_write tool (you will be asked to approve any shell commands)
- `/commit` — if you installed the sample commit skill during onboarding

## Workspace Files

Your workspace lives at `~/.munai/workspace/`. The most important files to customize:

| File | Purpose |
|------|---------|
| `SOUL.md` | The assistant's personality, voice, and tone |
| `USER.md` | Your name, timezone, preferences, and work context |
| `AGENTS.md` | Operating rules and boundaries for the agent |
| `MEMORY.md` | Persistent facts the agent accumulates over time |
| `HEARTBEAT.md` | Proactive tasks checked every 30 minutes |

Edit any of these with a text editor — changes take effect on the next conversation turn.

## Checking System Health

```bash
munai doctor
```

This checks your config, API key availability, workspace files, and connectivity to all configured providers.

## Next Steps

- [Configuration reference](configuration.md) — every `munai.json` option explained
- [Creating skills](creating-skills.md) — extend your assistant with new capabilities
- [Security model](security.md) — understand what munAI can and cannot do by default
- [Architecture overview](architecture.md) — how the components fit together
