"""Skills loader: scan workspace/skills/ for Markdown skill files."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


class Skill(BaseModel):
    name: str
    description: str = ""
    trigger: str | None = None
    tags: list[str] = Field(default_factory=list)
    required_env: list[str] = Field(default_factory=list)
    content: str  # markdown body after frontmatter
    file_path: Path


class SkillManifest:
    def __init__(self, skills: dict[str, Skill]) -> None:
        self._skills = skills

    def find_by_trigger(self, trigger: str) -> Skill | None:
        for skill in self._skills.values():
            if skill.trigger and skill.trigger == trigger:
                return skill
        return None

    def list_all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills


class SkillsLoader:
    @staticmethod
    def scan(skills_dir: Path) -> SkillManifest:
        """Walk skills_dir for *.md files and return a SkillManifest."""
        skills: dict[str, Skill] = {}

        if not skills_dir.exists():
            return SkillManifest(skills)

        for md_file in sorted(skills_dir.glob("*.md")):
            try:
                raw = md_file.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("Could not read skill file %s: %s", md_file, exc)
                continue

            skill = SkillsLoader._parse_skill(md_file, raw)
            skills[skill.name] = skill

        return SkillManifest(skills)

    @staticmethod
    def _parse_skill(path: Path, raw: str) -> Skill:
        """Parse a skill file, extracting optional YAML frontmatter."""
        m = _FRONTMATTER_RE.match(raw)

        if not m:
            # No frontmatter — use filename stem as name
            return Skill(name=path.stem, content=raw, file_path=path)

        frontmatter_text = m.group(1)
        content = raw[m.end():]

        try:
            import yaml  # type: ignore[import]
            fm = yaml.safe_load(frontmatter_text) or {}
        except Exception:
            log.warning("Failed to parse YAML frontmatter in %s; treating as no-frontmatter", path)
            return Skill(name=path.stem, content=raw, file_path=path)

        if not isinstance(fm, dict):
            return Skill(name=path.stem, content=raw, file_path=path)

        return Skill(
            name=str(fm.get("name", path.stem)),
            description=str(fm.get("description", "")),
            trigger=fm.get("trigger") or None,
            tags=[str(t) for t in (fm.get("tags") or [])],
            required_env=[str(k) for k in (fm.get("required_env") or [])],
            content=content,
            file_path=path,
        )
