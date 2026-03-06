"""CLI: munai sessions — browse past conversation sessions."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from ..agent.session import SESSIONS_DIR


def sessions_main(args: list[str]) -> None:
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  munai sessions               List recent sessions (newest first, max 20)\n"
            "  munai sessions <session-id>  Show a specific session\n"
        )
        return

    if args:
        _show_session(SESSIONS_DIR, args[0])
    else:
        _list_sessions(SESSIONS_DIR)


def _list_sessions(sessions_dir: Path) -> None:
    if not sessions_dir.exists():
        print("No sessions found (directory does not exist).")
        return

    files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("No sessions found.")
        return

    print(f"{'SESSION-ID':<10} {'MSGS':>4}  {'LAST-ACTIVE':<20}  PREVIEW")
    print("-" * 72)

    for path in files[:20]:
        session_id = path.stem
        events = _read_jsonl(path)

        msg_count = sum(1 for e in events if e.get("type") in ("user", "assistant"))
        last_ts = _last_active(events)
        preview = _last_user_preview(events, 40)

        sid_short = session_id[:8]
        print(f"{sid_short:<10} {msg_count:>4}  {last_ts:<20}  {preview}")


def _show_session(sessions_dir: Path, session_id: str) -> None:
    # Accept short IDs: match prefix
    matches = list(sessions_dir.glob(f"{session_id}*.jsonl")) if sessions_dir.exists() else []
    if not matches:
        print(f"Session not found: {session_id!r}", file=sys.stderr)
        sys.exit(1)
    path = matches[0]
    events = _read_jsonl(path)

    print(f"Session: {path.stem}")
    print("=" * 72)
    for event in events:
        role = event.get("type")
        if role not in ("user", "assistant"):
            continue
        text = event.get("text", "")
        label = "You" if role == "user" else "Munai"
        print(f"\n[{label}]")
        wrapped = textwrap.fill(text, width=80)
        print(wrapped)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return events


def _last_active(events: list[dict]) -> str:
    for event in reversed(events):
        ts = event.get("timestamp", "")
        if ts:
            return ts[:16].replace("T", " ")  # "YYYY-MM-DD HH:MM"
    return "—"


def _last_user_preview(events: list[dict], max_chars: int) -> str:
    for event in reversed(events):
        if event.get("type") == "user":
            text = event.get("text", "").replace("\n", " ").strip()
            if len(text) > max_chars:
                return text[:max_chars - 1] + "…"
            return text
    return ""
