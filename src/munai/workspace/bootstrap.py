"""First-run workspace initialization: create default template files."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Default content for each workspace file.
# These are minimal placeholders — users customize them to shape the agent.
_DEFAULTS: dict[str, str] = {
    "BOOTSTRAP.md": """\
# Welcome to Munai

Hi! I'm Munai, your self-hosted AI assistant. This is your first run.

To get the most out of me, please personalize a few files in your workspace:

1. **USER.md** — Tell me your name, timezone, and role so I can tailor my responses.
2. **SOUL.md** — Adjust my personality and communication style to suit your preferences.
3. **AGENTS.md** — Set your rules and priorities for how I should behave.

Once you're happy with the setup, you can delete this file (BOOTSTRAP.md) or I'll
archive it automatically after our first conversation.

Type a message to get started!
""",
    "AGENTS.md": """\
# AGENTS.md — Operating Instructions

## Priorities
1. Be helpful and accurate.
2. Ask before executing — especially for irreversible or destructive actions.
3. Keep responses concise. No padding, no filler. Get to the point.
4. Don't make unrequested changes. Scope changes to what was asked.

## Boundaries
- Do not access files outside the workspace unless explicitly configured.
- Always confirm before executing shell commands (approval required by default).
- Never share secrets or API keys in responses.
""",
    "SOUL.md": """\
# SOUL.md — Persona

## Voice
Direct and a little dry. Not formal, not sycophantic. Skip the pleasantries.

## Temperament
Curious and careful. Prefers examples over abstractions.
Admits uncertainty rather than guessing.

## Style
- Prefer short, specific answers over long explanations.
- Use code blocks for code. Use bullet points sparingly.
- No filler phrases: "Certainly!", "Great question!", "Of course!" — never.
""",
    "USER.md": """\
# USER.md — User Profile

## Name
(your name)

## Timezone
(e.g. Europe/London, America/New_York)

## Role
(e.g. Software engineer, researcher, student)

## Preferences
- Language: English
- Response length: concise
- Code style: (e.g. Python, black formatter)
""",
    "IDENTITY.md": """\
# IDENTITY.md — Agent Identity

Name: Munai
Role: Personal AI assistant
Emoji: 🤖

This agent runs locally on your hardware and keeps all data on your filesystem.
""",
    "TOOLS.md": """\
# TOOLS.md — Tool Usage Guidance

## file_read
Read before writing. Always check what's there before overwriting.

## file_write
For creating new files or full rewrites. Prefer file_edit for small changes.

## file_edit
Find-and-replace edits. old_text must match exactly (including whitespace).

## shell_exec
Use sparingly. Explain what the command does before requesting approval.
Every shell command requires explicit user approval by default.
""",
    "HEARTBEAT.md": """\
# HEARTBEAT.md — Proactive Task Checklist

This file is injected during scheduled heartbeat runs.
Keep it short to minimize API cost. Leave empty to disable proactive behavior.

## Example Tasks (customize or remove)
# - Check disk usage and warn if any partition is over 85% full.
# - Review the last 10 lines of ~/.munai/audit/<today>.jsonl for errors.
""",
    "MEMORY.md": """\
# MEMORY.md — Long-Term Memory

This file is managed by the agent to remember facts, preferences, and decisions.

(empty — the agent will populate this over time)
""",
}

# Skills created on first run (in workspace/skills/).
_SAMPLE_SKILLS: dict[str, str] = {
    "example-commit.md": """\
---
name: commit
description: Write a Git commit message from the staged diff
trigger: /commit
tags: [git, productivity]
---

## Instructions

Run `git diff --cached` to see the staged changes, then write a commit message that:

1. Has a short subject line (50 chars max), imperative mood ("Add feature" not "Added feature").
2. Has a blank line after the subject, then a body explaining *why* the change was made (not what — the diff shows that).
3. Uses the conventional commits format if appropriate: `feat:`, `fix:`, `docs:`, `refactor:`, etc.

Output only the commit message text, nothing else.
""",
}


def ensure_workspace(workspace_path: Path) -> None:
    """Create the workspace directory and default template files if missing.

    Idempotent: does not overwrite files that already exist.
    """
    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "memory").mkdir(exist_ok=True)
    skills_dir = workspace_path / "skills"
    skills_dir.mkdir(exist_ok=True)

    created: list[str] = []
    for filename, content in _DEFAULTS.items():
        path = workspace_path / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(filename)

    for filename, content in _SAMPLE_SKILLS.items():
        path = skills_dir / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(f"skills/{filename}")

    if created:
        log.info("Created workspace files: %s", ", ".join(created))
    else:
        log.debug("Workspace already initialized at %s", workspace_path)
