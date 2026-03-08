"""System prompt assembly from workspace bootstrap files and session history."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..skills.loader import Skill, SkillManifest, SkillsLoader

log = logging.getLogger(__name__)

# Hardcoded base system prompt — not user-editable.
_BASE_PROMPT = """\
You are Munai, a self-hosted personal AI assistant running on the user's own hardware.

## Core Behavior
- Be helpful, accurate, and concise.
- Think carefully before acting, especially for irreversible operations.
- When uncertain, say so rather than guessing.
- Keep responses focused on what was asked.

## Safety Constraints
- Never share API keys, tokens, passwords, or other secrets.
- Never access files outside the configured workspace without explicit permission.
- Always explain what a shell command does before requesting approval to run it.
- Do not attempt to exfiltrate data or make unexpected network connections.

## Output Format
- Use markdown formatting when it aids clarity (code blocks, lists, headers).
- For simple replies, plain text is fine.
- Keep responses appropriately concise — don't pad with unnecessary explanation.
"""

# Files injected into the system prompt, in order.
_BOOTSTRAP_FILES = [
    "BOOTSTRAP.md",
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "IDENTITY.md",
    "TOOLS.md",
    "MEMORY.md",
]


def _wrap(filename: str, content: str) -> str:
    return f"--- {filename} ---\n{content}\n---\n"


class ContextAssembler:
    """Assembles the system prompt and message history for an agent turn.

    System prompt injection order:
    1. Hardcoded base prompt
    2. AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md (always injected)
    3. MEMORY.md (injected if file exists)
    """

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._skill_manifest: SkillManifest | None = None

    def assemble(
        self, session_history: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Assemble context for a turn.

        Returns:
            (system_prompt, messages) where messages is a list of
            {"role": "user"|"assistant", "content": "..."} dicts
            suitable for pydantic-ai.
        """
        system_prompt = self._build_system_prompt()
        messages = self._build_messages(session_history)
        return system_prompt, messages

    def get_skill_for_message(self, text: str) -> Skill | None:
        """Return the skill matching the trigger at the start of text, or None."""
        if not text.startswith("/"):
            return None
        # The trigger is the first whitespace-delimited token
        trigger = text.split()[0]
        manifest = self._get_manifest()
        return manifest.find_by_trigger(trigger)

    def _get_manifest(self) -> SkillManifest:
        if self._skill_manifest is None:
            skills_dir = self._config.workspace_path / "skills"
            self._skill_manifest = SkillsLoader.scan(skills_dir)
        return self._skill_manifest

    def invalidate_skill_cache(self) -> None:
        """Force re-scan of skills on next access."""
        self._skill_manifest = None

    def _build_system_prompt(self) -> str:
        workspace = self._config.workspace_path
        parts: list[str] = [_BASE_PROMPT]
        total_bootstrap_chars = 0
        limit = self._config.bootstrap_total_max_chars
        per_file_limit = self._config.bootstrap_max_chars

        for filename in _BOOTSTRAP_FILES:
            path = workspace / filename
            if not path.exists():
                parts.append(f"[{filename}: not configured]\n")
                continue

            content = path.read_text(encoding="utf-8")
            if len(content) > per_file_limit:
                log.debug("Truncating %s at %d chars", filename, per_file_limit)
                content = content[:per_file_limit] + "\n[... truncated]"

            chunk = _wrap(filename, content)

            if total_bootstrap_chars + len(chunk) > limit:
                log.warning(
                    "Bootstrap total char limit (%d) reached before %s",
                    limit,
                    filename,
                )
                parts.append(f"[{filename}: omitted — bootstrap char limit reached]\n")
                continue

            parts.append(chunk)
            total_bootstrap_chars += len(chunk)

        # Inject skills manifest if any skills exist
        skills_section = self._build_skills_section()
        if skills_section:
            parts.append(skills_section)

        return "\n".join(parts)

    def _build_skills_section(self) -> str:
        manifest = self._get_manifest()
        skills = manifest.list_all()
        if not skills:
            return ""

        lines = ["--- SKILLS ---", "Available skills (invoke with /trigger-name):"]
        for skill in skills:
            trigger_label = skill.trigger if skill.trigger else f"/{skill.name}"
            desc = skill.description or skill.name
            lines.append(f"- {trigger_label}: {desc}")
        lines.append("---")
        section = "\n".join(lines)

        if len(section) > 5000:
            section = section[:5000] + "\n[... truncated]"
        return section

    def _build_messages(
        self, session_history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert session JSONL events to pydantic-ai message format.

        Handles compaction events: a compaction summary is injected as a
        user→assistant exchange so the LLM understands what happened before.
        """
        messages: list[dict[str, Any]] = []
        for event in session_history:
            event_type = event.get("type")
            if event_type == "user":
                messages.append({"role": "user", "content": event.get("text", "")})
            elif event_type == "assistant":
                messages.append(
                    {"role": "assistant", "content": event.get("text", "")}
                )
            elif event_type == "compaction":
                # Inject compaction summary as a synthetic exchange
                summary = event.get("summary", "")
                turns = event.get("turns_compacted", 0)
                messages.append({
                    "role": "user",
                    "content": f"[Earlier conversation summary — {turns} turns compacted]",
                })
                messages.append({
                    "role": "assistant",
                    "content": summary,
                })
            # tool_call, tool_result events are omitted (they appear in the
            # assistant's text response already)

        # Context guard: ~200k char limit (rough: chars/4 ≈ tokens)
        # Drop oldest pairs if over 80% of the limit.
        char_limit = 160_000
        total_chars = sum(len(m["content"]) for m in messages)
        while total_chars > char_limit and len(messages) >= 2:
            dropped = messages.pop(0)
            total_chars -= len(dropped["content"])
            if messages and messages[0]["role"] == "assistant":
                dropped = messages.pop(0)
                total_chars -= len(dropped["content"])
            log.debug("Context guard: dropped oldest turn (total_chars=%d)", total_chars)

        return messages

    def needs_compaction(
        self,
        session_history: list[dict[str, Any]],
        compaction_threshold: int = 120_000,
    ) -> bool:
        """Return True if the session history is large enough to warrant compaction.

        Compaction threshold is lower than the drop-threshold so we compact
        proactively rather than silently losing history.
        """
        total = sum(
            len(e.get("text", ""))
            for e in session_history
            if e.get("type") in ("user", "assistant")
        )
        return total > compaction_threshold
