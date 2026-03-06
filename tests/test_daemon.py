"""Tests for daemon.py: service file generation and installation."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from munai.cli.daemon import (
    generate_launchd_plist,
    generate_systemd_unit,
    install_launchd,
    install_systemd,
)


# ── generate_systemd_unit ─────────────────────────────────────────────────────

def test_generate_systemd_unit_contains_exe_path(tmp_path: Path):
    env_file = tmp_path / ".env"
    content = generate_systemd_unit("/usr/local/bin/munai", env_file)
    assert "/usr/local/bin/munai gateway" in content


def test_generate_systemd_unit_has_environment_file_line(tmp_path: Path):
    env_file = tmp_path / "custom.env"
    content = generate_systemd_unit("/usr/bin/munai", env_file)
    assert f"EnvironmentFile={env_file}" in content


def test_generate_systemd_unit_has_restart_policy(tmp_path: Path):
    content = generate_systemd_unit("/usr/bin/munai", tmp_path / ".env")
    assert "Restart=on-failure" in content


def test_generate_systemd_unit_has_install_section(tmp_path: Path):
    content = generate_systemd_unit("/usr/bin/munai", tmp_path / ".env")
    assert "[Install]" in content
    assert "WantedBy=default.target" in content


# ── generate_launchd_plist ────────────────────────────────────────────────────

def test_generate_launchd_plist_contains_exe_path():
    content = generate_launchd_plist("/usr/local/bin/munai", {})
    assert "/usr/local/bin/munai" in content
    assert "<string>gateway</string>" in content


def test_generate_launchd_plist_is_valid_xml():
    content = generate_launchd_plist("/usr/local/bin/munai", {"MY_KEY": "my_value"})
    # Should parse without errors
    root = ET.fromstring(content)
    assert root.tag == "plist"


def test_generate_launchd_plist_contains_env_vars():
    content = generate_launchd_plist("/usr/bin/munai", {"ANTHROPIC_API_KEY": "sk-test"})
    assert "ANTHROPIC_API_KEY" in content
    assert "sk-test" in content


def test_generate_launchd_plist_has_run_at_load():
    content = generate_launchd_plist("/usr/bin/munai", {})
    assert "<key>RunAtLoad</key>" in content


def test_generate_launchd_plist_has_label():
    content = generate_launchd_plist("/usr/bin/munai", {})
    assert "ai.munai.gateway" in content


# ── install_systemd ───────────────────────────────────────────────────────────

def test_install_systemd_writes_file_to_custom_dir(tmp_path: Path):
    env_file = tmp_path / ".env"
    unit_dir = tmp_path / "systemd" / "user"

    install_systemd("/usr/bin/munai", env_file, unit_dir=unit_dir)

    unit_file = unit_dir / "munai-gateway.service"
    assert unit_file.exists()
    content = unit_file.read_text()
    assert "ExecStart=/usr/bin/munai gateway" in content


def test_install_systemd_creates_parent_dirs(tmp_path: Path):
    env_file = tmp_path / ".env"
    unit_dir = tmp_path / "deeply" / "nested" / "dir"

    install_systemd("/usr/bin/munai", env_file, unit_dir=unit_dir)

    assert (unit_dir / "munai-gateway.service").exists()


# ── install_launchd ───────────────────────────────────────────────────────────

def test_install_launchd_writes_file_to_custom_dir(tmp_path: Path):
    agents_dir = tmp_path / "LaunchAgents"

    install_launchd("/usr/bin/munai", {"KEY": "value"}, agents_dir=agents_dir)

    plist_file = agents_dir / "ai.munai.gateway.plist"
    assert plist_file.exists()
    content = plist_file.read_text()
    assert "/usr/bin/munai" in content


def test_install_launchd_creates_parent_dirs(tmp_path: Path):
    agents_dir = tmp_path / "deep" / "agents"

    install_launchd("/usr/bin/munai", {}, agents_dir=agents_dir)

    assert (agents_dir / "ai.munai.gateway.plist").exists()
