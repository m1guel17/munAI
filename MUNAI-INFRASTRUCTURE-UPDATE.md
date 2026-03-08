# MUNAI-INFRASTRUCTURE-UPDATE.md

> **Purpose:** Specifies changes to munAI's codebase required to support Mission Control as an external consumer. These changes make munAI's internals usable as importable modules and stable APIs without changing any user-facing behavior.

---

## 1. Model Resolver as Importable Module

**Current state:** `src/munai/agent/model_resolver.py` is designed to be called internally by the agent runtime.

**Required change:** Refactor so that an external Python process (Mission Control) can import and use the model resolution logic without starting munAI's gateway or agent runtime.

**Specifically:**

```python
# External consumer (Mission Control) should be able to do:
from munai.agent.model_resolver import ModelResolver
from munai.config import load_config

config = load_config("~/.munai/munai.json")
resolver = ModelResolver(config.models)

# Get the active provider for a given role
provider = resolver.resolve_provider(role="primary")

# Build a request (returns url, headers, body)
url, headers, body = resolver.build_request(
    provider=provider,
    messages=[{"role": "user", "content": "Hello"}],
    tools=None,
)
```

**What this means for the codebase:**

- `ModelResolver` must have no side effects on instantiation (no gateway connection, no WebSocket, no global state).
- `load_config()` must be a pure function that reads the JSON5 file and returns a validated Pydantic model. No singletons.
- `build_request()` must be a pure function: takes config + messages + tools, returns URL + headers + body. No `aiohttp` session dependency — the caller provides their own HTTP client.
- `resolve_provider()` with failover state (cooldowns, backoff) should be a stateful class method, but the state must be instance-level (not module-level globals).

**Files to refactor:**

```
src/munai/config.py              # Ensure load_config() is importable with no side effects
src/munai/agent/model_resolver.py # Ensure ModelResolver class is self-contained
```

**Add to `pyproject.toml`:**

The munai package should be installable as a library dependency (not just as a CLI tool):

```toml
[project]
name = "munai"
# ... existing config ...

# Mission Control (and other external tools) can depend on munai:
# pip install munai
# from munai.config import load_config
# from munai.agent.model_resolver import ModelResolver
```

No new entry points needed. The existing `munai` CLI entry point is unaffected.

---

## 2. Config Schema as Stable Interface

**Current state:** `munai.json` schema is defined by Pydantic models in `config.py` but not documented as a public contract.

**Required change:** Document the config schema so Mission Control can reliably read it. This is a documentation + export task, not a code change.

**Specifically, export the Pydantic models so MC can validate:**

```python
# MC should be able to do:
from munai.config import MunaiConfig, ModelsConfig, ProviderConfig

# Read and validate munAI's config
config = MunaiConfig.model_validate_json(Path("~/.munai/munai.json").read_text())

# Access model providers
for name, provider in config.models.providers.items():
    print(f"{name}: {provider.base_url} / {provider.model}")
```

**What MC reads from munAI's config:**

| Field | What MC Uses It For |
|---|---|
| `models.providers` | Discover available LLM providers + their base URLs, auth, models |
| `models.primary` | Know which provider to use by default for leader/workers |
| `models.fallback` | Use the same failover chain |
| `tools.workspace_only` | Apply the same filesystem restriction logic |
| `tools.shell_approval_mode` | MC will set its own policy but needs to know munAI's defaults |

**What MC does NOT read:**

| Field | Reason |
|---|---|
| `channels.*` | MC accesses channels via munAI's WebSocket API, not by reading channel config |
| `gateway.*` | MC has its own gateway |
| `heartbeat.*` | MC has its own heartbeat per workspace |
| `audit.*` | MC has its own audit config |

---

## 3. Audit Event Schema as Shared Spec

**Current state:** Audit events are defined as Pydantic models in `src/munai/audit/schemas.py`.

**Required change:** Export the `AuditEvent` base model and event type constants so MC can write audit events in the exact same format. This allows a single audit viewer to search across both munAI and MC audit logs.

```python
# MC should be able to do:
from munai.audit.schemas import AuditEvent

event = AuditEvent(
    timestamp=datetime.utcnow(),
    event_type="mc.task.created",
    session_id="workspace:beauty-salon-app:leader",
    channel=None,
    detail={
        "task_id": "task-001",
        "title": "Build database schema",
        "assigned_to": "backend-dev",
    },
    request_id=None,
)

# Write to MC's own audit file
with open(audit_path, "a") as f:
    f.write(event.model_dump_json() + "\n")
```

**MC-specific event types (prefixed with `mc.`):**

| Event Type | When |
|---|---|
| `mc.workspace.created` | New workspace created |
| `mc.workspace.status_change` | Workspace status changed (active → paused, etc.) |
| `mc.worker.created` | Leader created a new worker agent |
| `mc.task.created` | Leader created a task |
| `mc.task.assigned` | Task assigned to a worker |
| `mc.task.completed` | Worker completed a task |
| `mc.task.blocked` | Worker flagged task as blocked |
| `mc.task.escalated` | Leader escalated to user |
| `mc.escalation.responded` | User responded to an escalation |
| `mc.agent.model_call` | Any agent (leader or worker) called an LLM |
| `mc.agent.tool_call` | Any agent called a tool |

These use the same `AuditEvent` structure — only the `event_type` string and `detail` payload differ.

---

## 4. WebSocket `send` Method for External Clients

**Current state:** The munAI gateway already has a `send` WebSocket method that delivers messages to channels.

**Required change for v0.2:** Allow Mission Control to connect to munAI's gateway as an authenticated WebSocket client and use the `send` method to deliver escalation notifications to the user via Telegram/WebChat.

**MC as a munAI WS client:**

```python
# MC connects to munAI's gateway:
ws = await aiohttp.ClientSession().ws_connect(
    "ws://127.0.0.1:18700",
)

# Handshake
await ws.send_json({
    "type": "connect",
    "client_id": "mission-control",
    "client_type": "external_app",
    "auth": {"token": os.environ["MUNAI_GATEWAY_TOKEN"]},
})

# Wait for connect-ok
response = await ws.receive_json()
assert response["type"] == "res" and response["ok"]

# Send an escalation notification via Telegram
await ws.send_json({
    "type": "req",
    "id": "mc-notif-001",
    "method": "send",
    "params": {
        "channel": "telegram",
        "to": "owner",  # send to the configured owner
        "text": "🎯 Mission Control: Leader in 'beauty-salon-app' needs your input:\n\n\"Stripe or MercadoPago for payment integration?\"",
    },
    "idempotency_key": "mc-esc-beauty-salon-001",
})
```

**What munAI needs to support:**

- A `client_type: "external_app"` in the connect handshake that is recognized and allowed (currently only `webchat`, `cli`, `channel_adapter` are documented).
- The `send` method must work for external clients, not just internal channel adapters.
- Auth token is mandatory for external clients (even on loopback).

**This is a v0.2 change.** For munAI v0.1, no external client support is needed. Add it when Mission Control Phase 3 implements the channel bridge.

---

## 5. Mission Control Skill for munAI (v0.2)

A skill file that lets users interact with Mission Control through their munAI personal assistant.

**File:** `~/.munai/workspace/skills/mission-control/SKILL.md`

```markdown
---
name: mission-control
description: Create and manage Mission Control workspaces via your personal assistant
requires:
  env:
    - MC_GATEWAY_TOKEN
  bins:
    - curl
---

# Mission Control Integration

When the user asks about workspaces, project teams, or multi-agent tasks,
use the Mission Control API to manage workspaces.

## API Base URL

http://127.0.0.1:18800/api

## Authentication

Include header: Authorization: Bearer $MC_GATEWAY_TOKEN

## Available Actions

### List Workspaces
GET /api/workspaces
Returns: list of workspace objects with name, status, worker count, task summary

### Create Workspace
POST /api/workspaces
Body: { "name": "...", "description": "...", "leader_soul": "...", "leader_agents": "...", "user_md": "..." }

### Get Workspace Status
GET /api/workspaces/{name}
Returns: full workspace detail including agents, tasks, escalations

### Respond to Escalation
POST /api/workspaces/{name}/escalations/{id}/respond
Body: { "response": "Use Stripe for payment integration." }

### Pause / Resume Workspace
POST /api/workspaces/{name}/pause
POST /api/workspaces/{name}/resume

## Usage Guidelines

- When the user says "create a workspace for X" → use Create Workspace
- When the user says "what's happening with my projects?" → use List Workspaces
- When the user says "check on the salon app" → use Get Workspace Status
- If there are pending escalations, mention them proactively
- Always confirm workspace creation parameters before calling the API
```

This skill is installed by the user (or by the Mission Control onboard wizard). It is NOT bundled with munAI — it's distributed with Mission Control.

---

## Summary of munAI Changes by Phase

### munAI v0.1 (no changes needed)

Mission Control v0.1 reads munAI's config file directly from disk and imports munAI's Python modules. No munAI code changes required if the modules are already clean and importable.

**Verification:** Test that the following works from an external Python script:

```python
from munai.config import load_config
from munai.agent.model_resolver import ModelResolver
from munai.audit.schemas import AuditEvent
```

If these imports fail (due to side effects, missing __init__.py exports, or circular dependencies), refactor to make them work. This is the only v0.1 action item.

### munAI v0.2 (for Mission Control Phase 3)

1. Add `client_type: "external_app"` support to the gateway WebSocket handshake.
2. Allow external clients to use the `send` WS method for channel delivery.
3. Document the `send` method parameters for external callers.
4. Test: MC connects to munAI gateway, sends a message via Telegram, message arrives on user's phone.
