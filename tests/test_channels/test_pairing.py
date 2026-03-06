"""Tests for PairingManager (Telegram pairing codes + allowed-user list)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from munai.channels.pairing import PairingManager


@pytest.fixture
def pairing_file(tmp_path: Path) -> Path:
    return tmp_path / "pairing.json"


@pytest.fixture
def mgr(pairing_file: Path) -> PairingManager:
    return PairingManager(pairing_file)


# ─── Code generation ─────────────────────────────────────────────────────────

def test_generate_code_is_6_chars_alphanumeric(mgr: PairingManager):
    code = mgr.generate_code()
    assert len(code) == 6
    assert code.isalnum()
    assert code == code.upper()


def test_generate_code_is_stored(mgr: PairingManager, pairing_file: Path):
    import json
    code = mgr.generate_code()
    data = json.loads(pairing_file.read_text())
    assert data["pending_code"] == code
    assert "code_expires_at" in data


def test_generate_code_refreshes_expiry(mgr: PairingManager):
    """Calling generate_code() twice replaces the old code and resets expiry."""
    mgr.generate_code()
    code2 = mgr.generate_code()
    assert mgr._data["pending_code"] == code2


# ─── verify_and_approve ──────────────────────────────────────────────────────

def test_verify_valid_code_returns_true_and_adds_user(mgr: PairingManager):
    code = mgr.generate_code()
    result = mgr.verify_and_approve(code, "12345678")
    assert result is True
    assert mgr.is_allowed("12345678")


def test_verify_wrong_code_returns_false(mgr: PairingManager):
    mgr.generate_code()
    result = mgr.verify_and_approve("ZZZZZZ", "12345678")
    assert result is False
    assert not mgr.is_allowed("12345678")


def test_verify_case_insensitive(mgr: PairingManager):
    """Code verification should be case-insensitive."""
    code = mgr.generate_code()
    result = mgr.verify_and_approve(code.lower(), "99")
    assert result is True


def test_verify_expired_code_returns_false(mgr: PairingManager):
    """Manipulate the expiry to be in the past."""
    import json
    code = mgr.generate_code()
    # Set expiry to the past
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    mgr._data["code_expires_at"] = past
    mgr._save()

    result = mgr.verify_and_approve(code, "12345678")
    assert result is False
    # Code should be cleared after expiry detection
    assert "pending_code" not in mgr._data


def test_verify_with_no_code_returns_false(mgr: PairingManager):
    result = mgr.verify_and_approve("ABC123", "user1")
    assert result is False


def test_verify_clears_code_after_success(mgr: PairingManager):
    """Once a code is used, it should be cleared."""
    code = mgr.generate_code()
    mgr.verify_and_approve(code, "user1")
    # Code should no longer be present
    assert "pending_code" not in mgr._data


# ─── is_allowed / get_allowed_users ──────────────────────────────────────────

def test_is_allowed_after_pairing(mgr: PairingManager):
    code = mgr.generate_code()
    mgr.verify_and_approve(code, "42")
    assert mgr.is_allowed("42") is True


def test_is_allowed_unknown_user_false(mgr: PairingManager):
    assert mgr.is_allowed("unknown_user") is False


def test_get_allowed_users_returns_copy(mgr: PairingManager):
    code = mgr.generate_code()
    mgr.verify_and_approve(code, "u1")
    users = mgr.get_allowed_users()
    assert "u1" in users
    # Mutating the returned list should not affect the manager
    users.append("injected")
    assert "injected" not in mgr.get_allowed_users()


# ─── Persistence ─────────────────────────────────────────────────────────────

def test_pairing_persists_across_instances(pairing_file: Path):
    """Allowed users should survive a new PairingManager instance."""
    mgr1 = PairingManager(pairing_file)
    code = mgr1.generate_code()
    mgr1.verify_and_approve(code, "persistent_user")

    mgr2 = PairingManager(pairing_file)
    assert mgr2.is_allowed("persistent_user")


def test_new_instance_with_missing_file_returns_empty(tmp_path: Path):
    mgr = PairingManager(tmp_path / "nonexistent.json")
    assert mgr.get_allowed_users() == []
    assert mgr.is_allowed("anyone") is False


def test_duplicate_pairing_does_not_duplicate_user(mgr: PairingManager):
    """Pairing the same user twice should not create duplicate entries."""
    code1 = mgr.generate_code()
    mgr.verify_and_approve(code1, "u1")
    code2 = mgr.generate_code()
    mgr.verify_and_approve(code2, "u1")
    assert mgr.get_allowed_users().count("u1") == 1
