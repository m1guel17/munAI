"""Session compaction: summarize old turns to reclaim context window space."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .. import llm_client

log = logging.getLogger(__name__)

# How many turns to include in a single compaction batch.
COMPACTION_BATCH_TURNS = 10

# System prompt for the compaction LLM call.
_COMPACTION_PROMPT = """\
You are a summarization assistant. The following is a portion of a conversation history.
Produce a concise summary that preserves:
- All key facts discussed
- Decisions made
- Files created, modified, or deleted (with exact names and paths)
- User preferences and stated constraints
- Any errors or issues encountered

Write in past tense. Be specific. Omit pleasantries and meta-commentary.
The summary will replace these turns in an AI assistant's context window.
"""


class Compactor:
    """Summarizes old conversation turns using the LLM.

    Compaction workflow:
    1. Identify the oldest batch of turns in the session.
    2. Call the LLM with a summarization prompt.
    3. Return the summary text and the number of turns replaced.
    4. The caller writes a ``compaction`` event to the session JSONL.
    """

    def __init__(self, model_resolver: Any) -> None:
        self._resolver = model_resolver

    async def compact(
        self,
        turns: list[dict[str, Any]],
        batch_size: int = COMPACTION_BATCH_TURNS,
    ) -> tuple[str, int]:
        """Summarize the oldest *batch_size* turns.

        Args:
            turns: Full session history as a list of event dicts.
            batch_size: Number of turns to compact.

        Returns:
            (summary_text, turns_compacted) — the number of turns removed.
        """
        # Collect user/assistant pairs from the beginning
        batch: list[dict[str, Any]] = []
        for event in turns:
            if event.get("type") in ("user", "assistant"):
                batch.append(event)
            if len(batch) >= batch_size:
                break

        if not batch:
            return "", 0

        # Build a readable transcript for the compaction prompt
        transcript_lines: list[str] = []
        for event in batch:
            role = event.get("type", "unknown").upper()
            text = event.get("text", "")
            transcript_lines.append(f"[{role}]: {text}")
        transcript = "\n\n".join(transcript_lines)

        try:
            client, model, provider = self._resolver.get_client(0)
            summary = await llm_client.generate(
                client,
                model,
                [{"role": "user", "content": f"Summarize the following conversation:\n\n{transcript}"}],
                system=_COMPACTION_PROMPT,
                timeout=float(provider.timeout_seconds),
            )
        except Exception as exc:
            log.error("Compaction LLM call failed: %s", exc)
            # Fallback: produce a minimal placeholder rather than crashing
            summary = (
                f"[Compaction failed — {len(batch)} turns removed. "
                f"Reason: {exc}]"
            )

        log.info("Compacted %d turns", len(batch))
        return summary, len(batch)


def apply_compaction(
    history: list[dict[str, Any]],
    summary: str,
    turns_compacted: int,
    session_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace the oldest *turns_compacted* user/assistant events with a compaction marker.

    Returns:
        (new_history, compaction_event) — the modified history and the event
        to append to the session JSONL file.
    """
    # Remove the first turns_compacted user/assistant events
    remaining = list(history)
    removed = 0
    new_history: list[dict[str, Any]] = []

    for event in remaining:
        if removed < turns_compacted and event.get("type") in ("user", "assistant"):
            removed += 1
        else:
            new_history.append(event)

    compaction_event: dict[str, Any] = {
        "type": "compaction",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "turns_compacted": removed,
    }

    # Prepend the compaction event so it appears at the start of what remains
    new_history = [compaction_event] + new_history
    return new_history, compaction_event
