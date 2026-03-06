# Security Model

munAI is a self-hosted agent that can read files and run shell commands on your machine. This document explains the default security posture, the threat model, and how to harden or relax the defaults.

## Default Posture

Every security-sensitive setting defaults to the most restrictive option. You opt *in* to risk, never out of safety.

| Feature | Default | Rationale |
|---|---|---|
| Gateway bind | `127.0.0.1` (loopback only) | No network exposure unless you explicitly configure remote access |
| Gateway auth token | Required if bind is non-loopback | Prevents unauthenticated access from the local network |
| File tool scope | `workspace_only: true` | The agent cannot read or write outside `~/.munai/workspace/` |
| Shell approval | `always` | Every `shell_exec` call requires your explicit approval |
| Channel DM policy | `pairing` | Unknown senders must complete a pairing handshake before they can interact |
| Audit logging | `enabled: true` | All tool calls and LLM requests are logged |
| Secret redaction | Enabled | API keys, tokens, and passwords are scrubbed from logs and tool output |
| Skills | None pre-installed | You consciously install each new capability |
| Heartbeat | Enabled but `HEARTBEAT.md` is empty | Scheduler runs but makes no API calls until you configure tasks |

## What the Agent Can Do

With default settings:

- **Read files** within `~/.munai/workspace/` only
- **Write and edit files** within `~/.munai/workspace/` only
- **Run shell commands** only after you click "Approve" in the WebChat UI
- **Interact** only with senders who have completed the pairing handshake

The agent **cannot**:
- Read `/etc/passwd`, your SSH keys, or any file outside the workspace
- Run shell commands without your approval (by default)
- Accept messages from unknown Telegram users without pairing

## Threat Model

### Prompt Injection

**Threat:** A malicious message tricks the agent into taking unintended actions.

**Mitigations:**
- Channel allowlists + pairing limit who can send messages to the agent
- Group messages (Telegram) require an @mention to activate
- The agent's system prompt includes injection-resistance instructions
- Tool policy gates what the agent can do even if it is tricked

### Malicious Skill

**Threat:** A skill file contains instructions that abuse the agent's capabilities.

**Mitigations:**
- Skills are **not executable code** — they are Markdown text injected into the system prompt
- Skills can only leverage existing tools (file read/write/edit, shell exec)
- The tool policy (`workspace_only`, `shell_approval_mode`) applies equally to skill-driven actions
- Every action is logged in the audit trail

### Runaway Agent

**Threat:** The agent enters an infinite loop or makes excessive API calls.

**Mitigations:**
- Maximum 25 tool calls per turn (configurable via `agent.max_tool_iterations`)
- Maximum 5-minute turn duration (configurable via `agent.max_turn_duration_seconds`)
- Heartbeat runs use a cheaper model (`models.heartbeat`) to limit cost
- Token and cost data is tracked in the audit log
- The Kill Switch in the WebChat Control Panel aborts all running sessions immediately

### Path Traversal

**Threat:** A tool call attempts to access `../../etc/passwd` or similar.

**Mitigation:** File tools resolve symlinks and verify the resulting path begins with the workspace root before executing. This is enforced at the `PathSandbox` level, not just by checking the input string.

### Credential Leakage

**Threat:** An API key or password appears in tool output or audit logs.

**Mitigations:**
- API keys are stored in environment variables only — never as plaintext in `munai.json`
- `tools.redact_patterns` (default: common key/token/password patterns) scrubs matches from tool output before it reaches the LLM or the audit log
- `~/.munai/.env` has file permissions `0600` (set by the onboarding wizard)

### Unauthorized Gateway Access

**Threat:** Someone on your local network connects to the gateway.

**Mitigations:**
- Default bind is `127.0.0.1` (loopback only). The gateway is not reachable from other machines.
- If you change `bind` to `0.0.0.0`, the config requires `token_env` to be set. Non-loopback without a token is rejected at startup.

## What We Explicitly Do Not Trust

- **Incoming messages** from any channel — always treated as untrusted user input
- **Skill files** — treated as user-provided prompt text, never executed directly
- **LLM output** — tool calls are validated against schema and policy before execution
- **Tool output** — sanitized, truncated, and redacted before feeding back to the LLM or writing to the audit log

## Hardening Checklist

For a more paranoid setup:

- [ ] Set `shell_approval_mode: "always"` (already the default)
- [ ] Set `workspace_only: true` (already the default)
- [ ] Set `dm_policy: "pairing"` or `"closed"` for Telegram (pairing is the default)
- [ ] Use `allow_from` to allowlist specific Telegram user IDs
- [ ] Set a strong `MUNAI_GATEWAY_TOKEN` if you expose the gateway beyond loopback
- [ ] Review the audit log regularly: `munai audit --date today`
- [ ] Run `munai doctor` after any configuration change
- [ ] Keep `redact_patterns` up to date if you handle unusual secret formats

## Relaxing Defaults

For trusted local environments (e.g., a dev machine you fully control):

```json5
{
  tools: {
    shell_approval_mode: "never", // Skip approval prompts
    workspace_only: false,        // Allow file access outside workspace
  },
}
```

If you set `workspace_only: false`, the agent can read and write anywhere your OS user can. Use with caution.

## Audit Log

The audit log at `~/.munai/audit/<YYYY-MM-DD>.jsonl` records every significant action:

```bash
munai audit --date today                        # Today's events
munai audit --type tool.call                    # Only tool executions
munai audit --type gateway.auth_fail            # Authentication failures
munai audit --follow                            # Live tail
```

Security events (`tool.blocked`, `tool.path_violation`, `gateway.auth_fail`) are highlighted in red in the WebChat audit viewer.

**Retention:** Default 90 days. Configurable via `audit.retention_days`. Old files are deleted at gateway startup.
