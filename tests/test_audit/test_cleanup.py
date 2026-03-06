"""Tests for AuditLogger.cleanup_old_logs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from munai.audit.logger import AuditLogger


def _make_logger(audit_dir: Path) -> AuditLogger:
    return AuditLogger(audit_dir=audit_dir, enabled=False)


def _write_log(audit_dir: Path, date_str: str, content: str = '{"event":"test"}\n') -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{date_str}.jsonl"
    path.write_text(content, encoding="utf-8")
    return path


def _days_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%d")


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_deletes_old_files(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    logger = _make_logger(audit_dir)

    old_file = _write_log(audit_dir, _days_ago(100))
    assert old_file.exists()

    deleted = await logger.cleanup_old_logs(retention_days=90)
    assert deleted == 1
    assert not old_file.exists()


@pytest.mark.asyncio
async def test_cleanup_preserves_recent_files(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    logger = _make_logger(audit_dir)

    recent_file = _write_log(audit_dir, _days_ago(5))
    assert recent_file.exists()

    deleted = await logger.cleanup_old_logs(retention_days=90)
    assert deleted == 0
    assert recent_file.exists()


@pytest.mark.asyncio
async def test_cleanup_skips_non_jsonl_files(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    logger = _make_logger(audit_dir)

    # Write a non-matching file
    stray = audit_dir / "notes.txt"
    stray.write_text("some notes", encoding="utf-8")

    deleted = await logger.cleanup_old_logs(retention_days=1)
    assert deleted == 0
    assert stray.exists()


@pytest.mark.asyncio
async def test_cleanup_returns_count(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    logger = _make_logger(audit_dir)

    _write_log(audit_dir, _days_ago(200))
    _write_log(audit_dir, _days_ago(150))
    _write_log(audit_dir, _days_ago(10))  # recent — should NOT be deleted

    deleted = await logger.cleanup_old_logs(retention_days=90)
    assert deleted == 2


@pytest.mark.asyncio
async def test_cleanup_empty_dir_returns_zero(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    # Don't create the directory
    logger = _make_logger(audit_dir)
    deleted = await logger.cleanup_old_logs(retention_days=90)
    assert deleted == 0


@pytest.mark.asyncio
async def test_cleanup_skips_non_date_jsonl(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    logger = _make_logger(audit_dir)

    # File has .jsonl extension but doesn't match YYYY-MM-DD pattern
    stray = audit_dir / "backup.jsonl"
    stray.write_text("{}", encoding="utf-8")

    deleted = await logger.cleanup_old_logs(retention_days=0)
    assert deleted == 0
    assert stray.exists()
