"""CLI: munai skills — list and inspect workspace skills."""
from __future__ import annotations

import sys

from ..config import load_config_or_defaults
from ..skills.loader import SkillsLoader


def skills_main(args: list[str]) -> None:
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  munai skills             List all skills in workspace/skills/\n"
            "  munai skills <name>      Show full content of a skill\n"
        )
        return

    config = load_config_or_defaults()
    skills_dir = config.agent.workspace_path / "skills"
    manifest = SkillsLoader.scan(skills_dir)

    if args:
        name = args[0]
        skill = manifest.skills.get(name)
        if skill is None:
            # Try by trigger
            skill = manifest.find_by_trigger(name if name.startswith("/") else f"/{name}")
        if skill is None:
            print(f"Skill not found: {name!r}", file=sys.stderr)
            print("Run 'munai skills' to list available skills.", file=sys.stderr)
            sys.exit(1)

        print(f"Name:        {skill.name}")
        print(f"Trigger:     {skill.trigger or '(none)'}")
        print(f"Description: {skill.description or '(none)'}")
        if skill.tags:
            print(f"Tags:        {', '.join(skill.tags)}")
        print(f"File:        {skill.file_path}")
        print()
        print("─" * 60)
        print(skill.content)
    else:
        _list_skills(manifest)


def _list_skills(manifest) -> None:
    skills = manifest.list_all()
    if not skills:
        print("No skills found. Add *.md files to your workspace/skills/ directory.")
        return

    print(f"{'NAME':<20}  {'TRIGGER':<15}  DESCRIPTION")
    print("-" * 68)
    for skill in skills:
        trigger = skill.trigger or "—"
        desc = skill.description or "—"
        if len(desc) > 40:
            desc = desc[:39] + "…"
        print(f"{skill.name:<20}  {trigger:<15}  {desc}")
