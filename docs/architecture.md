# Architecture Overview

munAI is a self-hosted AI assistant with two cleanly separated processes: the **Gateway** and the **Agent Runtime**. Neither knows the internals of the other — they communicate through well-defined async function calls.

## High-Level Structure

```
Telegram / WebChat / Future Channels
               │
               ▼
┌───────────────────────────────────────────────────┐
│                   GATEWAY                          │
│              (Python async process)                │
│                                                    │
│  Channel Adapters → Session Router → Lane Queue   │
│                                                    │
│  WebSocket Server (ws://127.0.0.1:18700/ws)        │
│  HTTP Server      (http://127.0.0.1:18700/)        │
│  Heartbeat Scheduler                               │
└────────────────────┬──────────────────────────────┘
                     │
                     ▼
┌───────────────────────────────────────────────────┐
│                AGENT RUNTIME                       │
│                                                    │
│  Context Assembler → Model Resolver → Tool Exec   │
│  Session Persister (JSONL)                        │
│  Audit Logger                                     │
└───────────────────────────────────────────────────┘
                     │
                     ▼
┌───────────────────────────────────────────────────┐
│                  FILESYSTEM (~/.munai/)             │
│                                                    │
│  munai.json         config                         │
│  workspace/         agent workspace files          │
│  sessions/          JSONL conversation transcripts │
│  audit/             JSONL daily audit logs         │
│  auth/              paired devices + allowlists    │
└───────────────────────────────────────────────────┘
```

## Gateway (`src/munai/gateway/`)

The Gateway is the single long-lived process. It owns all external connections and routes messages.

### Components

**`server.py` — GatewayServer**

The central coordinator. Starts all services, handles WebSocket connections, and dispatches requests to handler methods. There is one `GatewayServer` instance per process.

**`protocol.py` — Message schemas**

Pydantic models for the three WebSocket message types:
- `RequestMessage` — client → server (has `id`, `method`, `params`, optional `idempotency_key`)
- `ResponseMessage` — server → client (has matching `id`, `ok`, `payload` or `error`)
- `EventMessage` — server → client push (has `event`, `payload`, `seq`)

**`session_router.py` — SessionRouter**

Maps `session_key` (e.g., `webchat:abc-123`) to stable UUIDs. Persisted to `sessions/.routing.json` so sessions survive gateway restarts.

**`lane_queue.py` — LaneQueue**

One `asyncio.Queue` per session key. Messages for the same session are processed serially, preventing race conditions on session state.

**`auth.py` — GatewayAuth**

HMAC-based token validation for the WebSocket handshake. Used when the gateway is exposed beyond loopback.

**`approval.py` — ApprovalManager**

Manages pending `shell_exec` approval requests. The agent runtime pauses an `asyncio.Future` per command; the WebSocket handler resolves it when the user clicks Approve or Deny.

### Channel Adapters (`src/munai/channels/`)

Each adapter normalizes platform-specific messages into a `UnifiedMessage` schema and hands them to the session router.

- **`webchat.py`** — Messages arrive directly from the browser over the Gateway WebSocket.
- **`telegram.py`** — Long polling via `aiogram`. Handles DM policy, group @mentions.
- **`pairing.py`** — Manages the 6-character pairing code flow for unknown senders.

Adding a new channel requires implementing one class with three methods: `connect()`, `listen()`, `send()`.

### Heartbeat Scheduler (`src/munai/scheduler/heartbeat.py`)

Uses APScheduler (`AsyncIOScheduler`) to fire at a configurable interval (default: 30 minutes). On each tick:

1. Reads `HEARTBEAT.md` from the workspace. If empty, skips silently.
2. Runs the agent with the heartbeat content as the user prompt.
3. If the response contains `HEARTBEAT_OK`, suppresses delivery.
4. Otherwise, forwards the response to all paired Telegram users.

## Agent Runtime (`src/munai/agent/`)

The runtime is a **stateless function** that takes a message + session context and returns a response. It has no long-lived state — everything is loaded from and persisted to the filesystem on each turn.

### The Agentic Loop (`runtime.py`)

One turn = one full pass through the loop:

1. **Load session** — Read JSONL transcript from disk
2. **Assemble context** — Build system prompt from workspace files + session history
3. **Check context window** — Estimate token count; trigger compaction if over limit
4. **Resolve model** — Pick provider + model, check API key health
5. **Call LLM (streaming)** — Stream tokens; emit `agent.delta` events to Gateway
6. **Tool dispatch** — If the model requested tools: validate → audit → execute → feed result back → repeat from step 5
7. **Finalize** — Emit `agent.done`, append turn to JSONL, log token usage

**`context.py` — ContextAssembler**

Builds the system prompt by concatenating workspace files in a deterministic order: base prompt → `AGENTS.md` → `SOUL.md` → `USER.md` → `IDENTITY.md` → `TOOLS.md` → `MEMORY.md` → skills manifest → `HEARTBEAT.md` (heartbeat runs only). Each file is truncated at 20,000 characters; total bootstrap content is capped at 150,000 characters.

**`model_resolver.py` — ModelResolver**

Resolves which provider to use and builds the HTTP request. Importable standalone for external consumers (e.g., Mission Control):

```python
from munai.config import load_config
from munai.agent.model_resolver import ModelResolver

config = load_config("~/.munai/munai.json")
resolver = ModelResolver(config.models)
provider = resolver.resolve_provider(role="primary")
url, headers, body = resolver.build_request(provider, messages, tools)
```

Handles failover with exponential backoff (60s → 480s). Tracks cooldown state per provider instance.

**`session.py` — SessionManager**

Reads and writes JSONL session transcripts. Each line is a JSON object representing one event (user message, tool call, tool result, assistant response, or compaction summary).

**`compaction.py`**

When the context window guard detects the session history would exceed the model's context limit, it sends the oldest N turns to the LLM with a summarization prompt, then replaces them with a single `compaction` event.

## Tools (`src/munai/tools/`)

Tools are async Python functions registered with the agent runtime. Each tool has a typed JSON schema sent to the LLM for function calling.

| Tool | Description |
|---|---|
| `file_read` | Read file content. Images return base64. Supports line ranges. |
| `file_write` | Create or overwrite a file. |
| `file_edit` | Find-and-replace within a file. `old_text` must be unique. |
| `shell_exec` | Run a command list via subprocess. Returns stdout, stderr, exit code. |

**`policy.py` — PolicyChecker**

Gates tool calls against `ToolsConfig`. Raises `PolicyViolation` for denied tools or when `workspace_only` is violated.

**`sandbox.py` — PathSandbox**

Resolves symlinks and verifies the target path starts with the workspace root before any file operation. Raises `PermissionError` on violations.

## Audit System (`src/munai/audit/`)

Every significant action produces an append-only JSONL event at `~/.munai/audit/<YYYY-MM-DD>.jsonl`.

**`schemas.py`** — `AuditEvent` Pydantic model (importable by external tools):
```python
from munai.audit.schemas import AuditEvent
```

**`redactor.py`** — Scrubs regex-matched secrets from strings before they reach the audit log or the LLM.

**`logger.py`** — Async file writer. Flushes after every write (crash-safe). Handles cleanup of old log files.

## Config System (`src/munai/config.py`)

`load_config(path)` is a pure function — no singletons, no side effects. API keys are resolved from `os.environ` at call time via `ProviderConfig.resolve_api_key()`, never stored in the config model.

All Pydantic models are exported in `__all__` for external consumers:

```python
from munai.config import MunaiConfig, ModelsConfig, ProviderConfig, ApiFormat
```

## Web UI (`ui/`)

Static files served by the Gateway's HTTP server. No build step, no bundler, no framework.

The UI is a single-page app (`index.html`) with a sidebar nav. Each panel is a JS class:

| File | Panel |
|---|---|
| `chat.js` | Chat interface with streaming, tool cards, shell approval |
| `sessions.js` | Session list, switching, reset/compact/export |
| `health.js` | Gateway uptime, provider status |
| `audit.js` | Filtered audit log viewer with live tail |
| `usage.js` | Cost and token tracking |
| `tools.js` | Tool catalog and approval queue |
| `skills.js` | Installed skills browser |
| `channels.js` | Channel connection status |
| `cron.js` | Heartbeat scheduler management |
| `config.js` | Form and raw JSON config editor |
| `doctor.js` | Diagnostic checks |
| `devices.js` | Paired device management |

All state lives in `window.appState`. A single WebSocket connection (`ws.js`) is shared across all panels.

## Data Flow: One Turn

```
1. User types a message in WebChat
2. chat.js sends a "req" WS frame with method="agent"
3. GatewayServer.handle_websocket() dispatches to _handle_agent()
4. Message is enqueued in the LaneQueue for the session
5. AgentRuntime.run_turn() is called:
   a. Load JSONL history from disk
   b. Build system prompt from workspace files
   c. Call LLM (streaming)
   d. Stream tokens → emit "agent.delta" events → chat.js appends to DOM
   e. LLM requests a tool call → validate, audit, execute, feed result back → repeat
   f. LLM returns final text → emit "agent.done"
   g. Append full turn to JSONL
6. chat.js renders the complete response as Markdown
```

## Extension Points

- **New channel adapter** — Implement `connect()`, `listen()`, `send()` in `channels/`. Declare in `channels` config section.
- **New tool** — Add an async function in `tools/`, register its JSON schema. Update `ToolsConfig.allow` defaults.
- **New skill** — Drop a `SKILL.md` file in `workspace/skills/<name>/`. No code change required.
- **New LLM provider** — Add a `ProviderConfig` entry in `munai.json`. If the provider is OpenAI-compatible, no code change is needed.
