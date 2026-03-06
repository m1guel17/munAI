"""Append-only async JSONL audit logger with daily file rotation."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

from .redactor import Redactor
from .schemas import AuditEvent

log = logging.getLogger(__name__)

AUDIT_DIR = Path.home() / ".munai" / "audit"


class AuditLogger:
    """Append-only audit log writer.

    - One log file per calendar day (UTC): ``<audit_dir>/<YYYY-MM-DD>.jsonl``
    - File handle is kept open between writes and rotated at UTC midnight.
    - asyncio.Lock serializes writes to prevent interleaved lines.
    - flush() is called after every write: audit data must survive process crashes.
    """

    def __init__(
        self,
        audit_dir: Path = AUDIT_DIR,
        redactor: Redactor | None = None,
        enabled: bool = True,
    ) -> None:
        self._dir = audit_dir
        self._redactor = redactor
        self._enabled = enabled
        self._lock = asyncio.Lock()
        self._handle: IO[str] | None = None
        self._current_date: str | None = None

    async def log(
        self,
        event_type: str,
        detail: dict[str, Any] | None = None,
        session_id: str | None = None,
        channel: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        safe_detail: dict[str, Any] = detail or {}
        if self._redactor is not None:
            safe_detail = self._redactor.redact_dict(safe_detail)
        event = AuditEvent(
            event_type=event_type,
            session_id=session_id,
            channel=channel,
            detail=safe_detail,
            request_id=request_id,
        )
        async with self._lock:
            await self._write(event)

    async def _write(self, event: AuditEvent) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self._dir.mkdir(parents=True, exist_ok=True)
            log_path = self._dir / f"{today}.jsonl"
            self._handle = open(log_path, "a", encoding="utf-8")
            self._current_date = today
        assert self._handle is not None
        self._handle.write(event.to_jsonl_line())
        self._handle.flush()  # Must not buffer — audit data must survive crashes.

    async def cleanup_old_logs(self, retention_days: int) -> int:
        """Delete JSONL audit files older than retention_days days.

        Returns the count of deleted files.
        Only deletes files whose names match YYYY-MM-DD.jsonl.
        """
        _DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        deleted = 0

        async with self._lock:
            if not self._dir.exists():
                return 0
            for path in self._dir.iterdir():
                if not _DATE_PATTERN.match(path.name):
                    continue
                file_date = path.name[:10]  # "YYYY-MM-DD"
                if file_date < cutoff_str:
                    try:
                        path.unlink()
                        deleted += 1
                        log.debug("Deleted old audit file: %s", path.name)
                    except OSError as exc:
                        log.warning("Failed to delete audit file %s: %s", path.name, exc)

        return deleted

    async def close(self) -> None:
        async with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
