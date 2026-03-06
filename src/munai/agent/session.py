"""JSONL session persistence — read and append conversation turns."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".munai" / "sessions"


class SessionManager:
    """Read and append JSONL session files.

    Each session is a file at ``<sessions_dir>/<session_id>.jsonl``.
    One JSON object per line; lines are never modified after writing.

    Thread-safety: one asyncio.Lock per session file ensures no two
    coroutines write to the same file simultaneously.
    """

    def __init__(self, sessions_dir: Path = SESSIONS_DIR) -> None:
        self._dir = sessions_dir
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    async def load(self, session_id: str) -> list[dict[str, Any]]:
        """Load all events for a session. Returns [] if the file doesn't exist."""
        path = self._path(session_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        async with self._lock_for(session_id):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            log.warning("Skipping malformed JSONL line in %s", path)
        return events

    async def append(self, session_id: str, event: dict[str, Any]) -> None:
        """Append a single event to the session file.

        Creates the file and parent directory if they don't exist.
        Flushes after every write to survive process crashes.
        """
        path = self._path(session_id)
        async with self._lock_for(session_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
