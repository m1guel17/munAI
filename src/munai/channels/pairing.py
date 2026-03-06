"""Telegram pairing: one-time codes and persisted allowed-user list."""
from __future__ import annotations

import json
import random
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path


_CODE_LENGTH = 6
_CODE_EXPIRY_HOURS = 24


class PairingManager:
    """Manages Telegram pairing codes and the persistent list of approved users.

    Storage layout (``~/.munai/pairing.json``):
    ```json
    {
        "allowed_users": ["12345678"],
        "pending_code": "A7B2C9",
        "code_expires_at": "2026-03-04T12:00:00+00:00"
    }
    ```

    Thread-safety: single-process only (no asyncio.Lock needed — all operations
    are synchronous JSON file reads/writes, fast enough to run inline).
    """

    def __init__(self, pairing_file: Path) -> None:
        self._file = pairing_file
        self._data: dict = self._load()

    # ─── Public API ──────────────────────────────────────────────────────────

    def generate_code(self) -> str:
        """Generate a fresh 6-character pairing code valid for 24 hours.

        Calling this again before the previous code expires replaces the old one.
        """
        chars = string.ascii_uppercase + string.digits
        code = "".join(random.choices(chars, k=_CODE_LENGTH))
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_CODE_EXPIRY_HOURS)
        self._data["pending_code"] = code
        self._data["code_expires_at"] = expires_at.isoformat()
        self._save()
        return code

    def verify_and_approve(self, code: str, user_id: str) -> bool:
        """Check a pairing code submitted by a Telegram user.

        If valid and not expired, the user_id is added to ``allowed_users``,
        the code is cleared, and True is returned. Returns False otherwise.
        """
        pending = self._data.get("pending_code")
        expires_str = self._data.get("code_expires_at")

        if not pending or not expires_str:
            return False

        # Case-insensitive comparison
        if pending.upper() != code.strip().upper():
            return False

        try:
            expires_at = datetime.fromisoformat(expires_str)
        except ValueError:
            return False

        if datetime.now(timezone.utc) > expires_at:
            # Expired — clear it
            self._data.pop("pending_code", None)
            self._data.pop("code_expires_at", None)
            self._save()
            return False

        # Valid — approve the user
        allowed: list[str] = self._data.setdefault("allowed_users", [])
        if user_id not in allowed:
            allowed.append(user_id)
        self._data.pop("pending_code", None)
        self._data.pop("code_expires_at", None)
        self._save()
        return True

    def is_allowed(self, user_id: str) -> bool:
        """Return True if this Telegram user has been paired."""
        return user_id in self._data.get("allowed_users", [])

    def get_allowed_users(self) -> list[str]:
        """Return a copy of the current allowed-user list."""
        return list(self._data.get("allowed_users", []))

    def revoke(self, user_id: str) -> bool:
        """Remove a user from the allowed list. Returns True if the user was found."""
        allowed: list[str] = self._data.get("allowed_users", [])
        if user_id not in allowed:
            return False
        allowed.remove(user_id)
        self._data["allowed_users"] = allowed
        self._save()
        return True

    def get_pending_code(self) -> dict | None:
        """Return the active pending code with its expiry, or None if none exists."""
        code = self._data.get("pending_code")
        expires_str = self._data.get("code_expires_at")
        if not code or not expires_str:
            return None
        try:
            expires_at = datetime.fromisoformat(expires_str)
        except ValueError:
            return None
        if datetime.now(timezone.utc) > expires_at:
            return None
        return {"code": code, "expires_at": expires_str}

    # ─── Internal ────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._file.exists():
            return {"allowed_users": []}
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"allowed_users": []}
            return data
        except (OSError, json.JSONDecodeError):
            return {"allowed_users": []}

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
