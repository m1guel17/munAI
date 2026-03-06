"""Tests for SkillsLoader and SkillManifest."""
from __future__ import annotations

from pathlib import Path

import pytest

from munai.skills.loader import Skill, SkillManifest, SkillsLoader


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _write_skill(directory: Path, filename: str, content: str) -> Path:
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


_FRONTMATTER_SKILL = """\
---
name: commit
description: Write a Git commit message from staged diff
trigger: /commit
tags: [git, productivity]
---

## Instructions

Run git diff --cached, then write a commit message.
"""

_NO_FRONTMATTER_SKILL = """\
## Simple Skill

This skill has no frontmatter. Its name comes from the filename.
"""


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_scan_empty_dir_returns_empty_manifest(tmp_path: Path):
    manifest = SkillsLoader.scan(tmp_path)
    assert manifest.list_all() == []
    assert manifest.skills == {}


def test_scan_missing_dir_returns_empty_manifest(tmp_path: Path):
    manifest = SkillsLoader.scan(tmp_path / "nonexistent")
    assert manifest.list_all() == []


def test_scan_skill_with_frontmatter(tmp_path: Path):
    _write_skill(tmp_path, "commit.md", _FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    skills = manifest.list_all()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "commit"
    assert skill.description == "Write a Git commit message from staged diff"
    assert skill.trigger == "/commit"
    assert "git" in skill.tags
    assert "productivity" in skill.tags


def test_scan_skill_without_frontmatter_uses_stem_as_name(tmp_path: Path):
    _write_skill(tmp_path, "my-tool.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    skills = manifest.list_all()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "my-tool"
    assert skill.trigger is None
    assert skill.description == ""


def test_scan_multiple_skills(tmp_path: Path):
    _write_skill(tmp_path, "alpha.md", _FRONTMATTER_SKILL)
    _write_skill(tmp_path, "beta.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    names = [s.name for s in manifest.list_all()]
    # Should include "commit" (from frontmatter name) and "beta"
    assert "commit" in names
    assert "beta" in names


def test_find_by_trigger_returns_skill(tmp_path: Path):
    _write_skill(tmp_path, "commit.md", _FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    skill = manifest.find_by_trigger("/commit")
    assert skill is not None
    assert skill.name == "commit"


def test_find_by_trigger_missing_returns_none(tmp_path: Path):
    _write_skill(tmp_path, "commit.md", _FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    assert manifest.find_by_trigger("/nonexistent") is None


def test_skill_content_excludes_frontmatter(tmp_path: Path):
    _write_skill(tmp_path, "commit.md", _FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    skill = manifest.find_by_trigger("/commit")
    assert skill is not None
    # Content should not contain the frontmatter block
    assert "---" not in skill.content or "trigger" not in skill.content
    assert "Instructions" in skill.content


def test_list_all_sorted_by_name(tmp_path: Path):
    _write_skill(tmp_path, "z-skill.md", _NO_FRONTMATTER_SKILL)
    _write_skill(tmp_path, "a-skill.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    names = [s.name for s in manifest.list_all()]
    assert names == sorted(names)


def test_skill_file_path_is_set(tmp_path: Path):
    p = _write_skill(tmp_path, "mytool.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    skill = manifest.list_all()[0]
    assert skill.file_path == p


def test_scan_ignores_subdirectories(tmp_path: Path):
    """SkillsLoader.scan() is non-recursive — subdirectories are skipped."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_skill(sub, "nested.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    assert manifest.list_all() == []


def test_skill_tags_default_to_empty_list(tmp_path: Path):
    content = "---\nname: notag\ndescription: no tags here\n---\nbody\n"
    _write_skill(tmp_path, "notag.md", content)
    manifest = SkillsLoader.scan(tmp_path)
    skill = manifest.skills.get("notag")
    assert skill is not None
    assert skill.tags == []


def test_find_by_trigger_case_sensitive(tmp_path: Path):
    _write_skill(tmp_path, "commit.md", _FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    assert manifest.find_by_trigger("/Commit") is None
    assert manifest.find_by_trigger("/commit") is not None


def test_skill_without_trigger_not_findable(tmp_path: Path):
    _write_skill(tmp_path, "plain.md", _NO_FRONTMATTER_SKILL)
    manifest = SkillsLoader.scan(tmp_path)
    assert manifest.find_by_trigger("/plain") is None
