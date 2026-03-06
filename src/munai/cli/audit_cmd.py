"""CLI: munai audit — view audit log events."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..audit.logger import AUDIT_DIR


def audit_main(args: list[str]) -> None:
    date_str: str | None = None
    event_type_filter: str | None = None
    limit = 20
    follow = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(
                "Usage:\n"
                "  munai audit                         Last 20 events from today\n"
                "  munai audit --date YYYY-MM-DD       Specific date\n"
                "  munai audit --type <event-type>     Filter by event type prefix\n"
                "  munai audit --limit N               Number of events (default 20)\n"
                "  munai audit --follow                Tail mode (Ctrl+C to stop)\n"
            )
            return
        elif arg == "--date" and i + 1 < len(args):
            i += 1
            date_str = args[i]
        elif arg == "--type" and i + 1 < len(args):
            i += 1
            event_type_filter = args[i]
        elif arg == "--limit" and i + 1 < len(args):
            i += 1
            try:
                limit = int(args[i])
            except ValueError:
                print(f"Invalid --limit value: {args[i]!r}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--follow":
            follow = True
        i += 1

    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_path = AUDIT_DIR / f"{date_str}.jsonl"

    if follow:
        _tail_follow(log_path, event_type_filter)
    else:
        _print_events(log_path, event_type_filter, limit)


def _print_events(path: Path, type_filter: str | None, limit: int) -> None:
    events = _load_events(path, type_filter)
    events = events[-limit:]
    if not events:
        print(f"No events found in {path.name}.")
        return

    _print_header()
    for ev in events:
        _print_row(ev)


def _tail_follow(path: Path, type_filter: str | None) -> None:
    offset = 0
    _print_header()
    try:
        while True:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    f.seek(offset)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if type_filter and not ev.get("event_type", "").startswith(type_filter):
                            continue
                        _print_row(ev)
                    offset = f.tell()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_events(path: Path, type_filter: str | None) -> list[dict]:
    if not path.exists():
        return []
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if type_filter and not ev.get("event_type", "").startswith(type_filter):
                    continue
                events.append(ev)
    except OSError:
        pass
    return events


def _print_header() -> None:
    print(f"{'TIME':<8}  {'EVENT':<30}  {'SESSION':<10}  DETAIL")
    print("-" * 76)


def _print_row(ev: dict) -> None:
    ts = ev.get("timestamp", "")
    time_str = ts[11:19] if len(ts) >= 19 else ts[:8]  # "HH:MM:SS"
    event_type = ev.get("event_type", "")[:30]
    sid = (ev.get("session_id") or "")[:8] or "—"
    detail = json.dumps(ev.get("detail") or {})
    if len(detail) > 60:
        detail = detail[:59] + "…"
    print(f"{time_str:<8}  {event_type:<30}  {sid:<10}  {detail}")
