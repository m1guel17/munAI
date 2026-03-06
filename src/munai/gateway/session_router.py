"""Maps channel session keys to stable session UUIDs, persisted across restarts."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from ..agent.session import SessionManager

log = logging.getLogger(__name__)

ROUTING_FILE = Path.home() / ".munai" / "sessions" / ".routing.json"


class SessionRouter:
    """Maintains a stable mapping from session_key to session_id.

    session_key = "{channel}:{sender_id}"  e.g. "webchat:abc-123"
    session_id  = stable UUID, generated once and persisted

    The routing table is persisted to a JSON file so the same device
    reconnects to the same session after a gateway restart.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        routing_file: Path = ROUTING_FILE,
    ) -> None:
        self._session_manager = session_manager
        self._routing_file = routing_file
        self._table: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._routing_file.exists():
            try:
                with open(self._routing_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load routing file: %s", exc)
        return {}

    def _save(self) -> None:
        self._routing_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._routing_file, "w", encoding="utf-8") as f:
            json.dump(self._table, f, indent=2)

    def get_or_create_session(self, session_key: str) -> str:
        """Return the session_id for a session_key, creating one if needed."""
        if session_key not in self._table:
            session_id = str(uuid.uuid4())
            self._table[session_key] = session_id
            self._save()
            log.info("Created session %s for key %s", session_id, session_key)
        return self._table[session_key]

    def all_sessions(self) -> dict[str, str]:
        """Return a copy of the full routing table."""
        return dict(self._table)
