"""Secret redaction engine for audit logs and tool output."""
from __future__ import annotations

import re
from typing import Any

REPLACEMENT = "[REDACTED]"


class Redactor:
    """Recursively redacts secrets matching regex patterns from strings and dicts."""

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(p) for p in patterns]

    def redact_string(self, text: str) -> str:
        for pattern in self._patterns:
            text = pattern.sub(REPLACEMENT, text)
        return text

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact strings within a dict structure."""
        return self._walk(data)  # type: ignore[return-value]

    def _walk(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.redact_string(obj)
        if isinstance(obj, dict):
            return {k: self._walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._walk(item) for item in obj]
        return obj
