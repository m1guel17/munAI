"""Tests for gateway_cmd._load_dotenv."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from munai.cli.gateway_cmd import _load_dotenv


def test_load_dotenv_injects_vars(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("MY_DOTENV_KEY=hello\nOTHER_DOTENV=world\n")
    os.environ.pop("MY_DOTENV_KEY", None)
    os.environ.pop("OTHER_DOTENV", None)
    try:
        _load_dotenv(env_file)
        assert os.environ["MY_DOTENV_KEY"] == "hello"
        assert os.environ["OTHER_DOTENV"] == "world"
    finally:
        os.environ.pop("MY_DOTENV_KEY", None)
        os.environ.pop("OTHER_DOTENV", None)


def test_load_dotenv_does_not_overwrite_existing(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("MY_DOTENV_KEY=from_file\n")
    os.environ["MY_DOTENV_KEY"] = "from_env"
    try:
        _load_dotenv(env_file)
        assert os.environ["MY_DOTENV_KEY"] == "from_env"
    finally:
        os.environ.pop("MY_DOTENV_KEY", None)


def test_load_dotenv_missing_file_is_noop(tmp_path: Path):
    _load_dotenv(tmp_path / "nonexistent.env")  # must not raise


def test_load_dotenv_ignores_comments_and_blanks(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nDOTENV_KEY=val\n")
    os.environ.pop("DOTENV_KEY", None)
    try:
        _load_dotenv(env_file)
        assert os.environ["DOTENV_KEY"] == "val"
    finally:
        os.environ.pop("DOTENV_KEY", None)
