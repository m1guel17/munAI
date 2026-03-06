# Contributing to munAI

Thanks for your interest in contributing to munAI. This document explains how to get involved, what we expect from contributions, and how the review process works.

---

## Ways to Contribute

**Report bugs.** Open an issue with clear reproduction steps, your Python version, OS, and the relevant section of `munai doctor` output.

**Request features.** Open an issue describing the use case — what you're trying to accomplish and why the current system doesn't support it. Use cases are more helpful than solution proposals.

**Fix bugs or implement features.** Fork the repo, create a branch, make your changes, and open a pull request. See the workflow section below.

**Write or improve documentation.** Docs live in `docs/`. If something confused you during setup or usage, it probably confuses others too.

**Share skills.** If you've written a useful `SKILL.md`, open a PR adding it to the community skills directory. See the skills section below.

**Review pull requests.** Code review from the community is valuable, especially for security-sensitive changes.

---

## Development Setup

```bash
# Clone and set up
git clone https://github.com/m1guel17/munAI.git
cd munAI

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify everything works
pytest
munai --version
```

**Requirements:**
- Python 3.12+
- Git

**Dev dependencies** (installed with `[dev]`):
- `pytest` + `pytest-asyncio` for testing
- `ruff` for linting
- `mypy` for type checking

---

## Pull Request Workflow

1. **Fork the repo** and create a branch from `main`:
   ```bash
   git checkout -b fix/shell-approval-race-condition
   ```

   Branch naming: `fix/description`, `feat/description`, `docs/description`, `refactor/description`.

2. **Make your changes.** Keep PRs focused on a single concern. A PR that fixes a bug and also refactors an unrelated module will be asked to split.

3. **Write or update tests.** New features need tests. Bug fixes need a test that reproduces the bug and verifies the fix.

4. **Run the checks locally:**
   ```bash
   pytest                # all tests pass
   ruff check src/       # no lint errors
   ruff format src/      # code is formatted
   mypy src/munai/       # no type errors
   ```

5. **Write a clear PR description.** Explain what changed, why, and how to test it. If the change affects security or the audit system, call that out explicitly.

6. **Open the PR against `main`.** One of the maintainers will review it. Expect feedback — it's part of the process, not a judgment.

---

## Code Standards

### Style

- **Formatter:** `ruff format` (follows Black's style with default settings)
- **Linter:** `ruff check` with the project's config in `pyproject.toml`
- **Type hints:** Required on all public function signatures. Use `mypy` strict mode.
- **Docstrings:** Required on all public classes and functions. Use Google-style docstrings.

### Architecture Rules

These are non-negotiable. PRs that violate them will be asked to rework.

1. **No global mutable state.** All state lives in explicitly passed objects (config, session, workspace). No module-level singletons, no global dicts, no hidden caches.

2. **No side effects on import.** Importing any module must not start services, open connections, create files, or read environment variables. Side effects happen in explicit `init()` or `start()` calls.

3. **Every tool call must be auditable.** If you add a new tool, it must emit `tool.call` and `tool.result` audit events with full parameters. No silent actions.

4. **File tools must respect workspace containment.** Any new tool that touches the filesystem must go through the path containment check (`resolved path starts with workspace root`). No exceptions.

5. **Secrets never appear in config, logs, or LLM context as plaintext.** Use env var references for credentials. Apply redaction patterns to tool output. If you're unsure whether something is a secret, treat it as one.

6. **The gateway and agent runtime are separate concerns.** The gateway routes messages and manages sessions. The agent runtime reasons and executes tools. Don't mix them. If you need the agent to know about gateway state, pass it through the context assembly layer.

### Testing

- **Unit tests** go in `tests/test_<module>/`. Each test file mirrors the source file it tests.
- **Integration tests** that require a running gateway or real LLM API go in `tests/integration/` and are skipped by default (run with `pytest -m integration`).
- **Fixtures** live in `tests/conftest.py`. Prefer fixtures over setup/teardown methods.
- **Mock external services.** Tests must not make real API calls unless explicitly marked as integration tests. Mock LLM responses, mock Telegram API, mock filesystem operations where appropriate.

---

## Security-Sensitive Changes

The following areas require **extra scrutiny** during review. PRs touching these areas will be reviewed by a maintainer before merging, regardless of contributor experience.

- `src/munai/tools/` — Tool execution, policy enforcement, path containment
- `src/munai/tools/sandbox.py` — Subprocess isolation and environment control
- `src/munai/gateway/auth.py` — Authentication, pairing, token validation
- `src/munai/audit/` — Audit logging, redaction, retention
- `src/munai/config.py` — Config loading (especially env var resolution)
- Any change to default security settings in the config schema

If your PR modifies security behavior:
- Explain the security impact in the PR description
- Add a test that verifies the security property is maintained
- If you're relaxing a restriction, justify why the tradeoff is acceptable

---

## Adding a New Tool

If you want to add a new tool to the agent:

1. Create `src/munai/tools/your_tool.py` implementing the tool function.
2. Register it in `src/munai/tools/__init__.py`.
3. Add it to the tool policy system — decide its default allow/deny status.
4. Emit `tool.call` and `tool.result` audit events (use the existing tools as a pattern).
5. If the tool accesses the filesystem, enforce workspace containment.
6. If the tool makes network requests, document what it connects to.
7. Add the tool name to the `PROVIDER_PRESETS` if it should appear in `munai models add` or onboard.
8. Write tests covering: successful execution, failure handling, policy denial, and audit event emission.
9. Update `docs/` with the tool's description and parameters.

---

## Adding a New Channel Adapter

If you want to add a new messaging channel:

1. Create `src/munai/channels/your_channel.py` inheriting from the base adapter.
2. Implement `connect()`, `listen()`, and `send()`.
3. Add the channel to config validation in `config.py`.
4. Add it to the onboard wizard's channel selection.
5. Write tests with mocked platform API.
6. Document setup instructions in `docs/channels/`.

The adapter must normalize all incoming messages into `UnifiedMessage` format and handle outbound delivery through `OutboundMessage`. The gateway should not need to know any channel-specific details.

---

## Community Skills

Skills are Markdown files that teach the agent new capabilities. To contribute a skill:

1. Create a directory: `community-skills/your-skill-name/SKILL.md`
2. Include YAML frontmatter with `name`, `description`, and `requires` (env vars, binaries).
3. Write clear instructions that the agent can follow using its existing tools.
4. Test the skill with your own munAI instance.
5. Open a PR adding the skill.

**Skills must not:**
- Instruct the agent to disable security settings
- Reference hardcoded API keys or credentials
- Instruct the agent to access files outside the workspace without clear user consent
- Include instructions designed to override the agent's system prompt

Skills that violate these rules will be rejected.

---

## Issue Labels

| Label | Meaning |
|---|---|
| `bug` | Something is broken |
| `feature` | New capability request |
| `security` | Security-related issue or improvement |
| `docs` | Documentation improvement |
| `good first issue` | Suitable for new contributors |
| `help wanted` | Maintainers would appreciate community help |
| `breaking` | Change that affects existing users' config or behavior |

---

## Code of Conduct

Be respectful. Be constructive. Assume good intent. We're all here to build something useful.

If someone's behavior is making the project unwelcoming, contact the maintainers privately at the email in the GitHub profile.

---

## Questions?

Open a discussion in [GitHub Discussions](https://github.com/m1guel17/munAI/discussions) or ask in an issue. There are no dumb questions — if the docs didn't answer it, the docs need improvement.