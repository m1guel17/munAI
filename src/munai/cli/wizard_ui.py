"""Display layer for the onboarding wizard.

Wraps rich (panels, spinners, colored rail output) and questionary (prompts)
into a WizardUI class. When ``interactive=False`` all prompts return their
default values without any terminal interaction, enabling non-interactive / CI
usage.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console

import questionary
from questionary import Style

# ── questionary style ────────────────────────────────────────────────────────

MUNAI_STYLE = Style([
    ("qmark", "fg:cyan bold"),        # ◆ active marker
    ("question", "fg:white bold"),    # question text
    ("answer", "fg:green bold"),      # echoed answer
    ("pointer", "fg:cyan bold"),      # ● active item
    ("highlighted", "fg:cyan bold"),  # highlighted item
    ("selected", "fg:green"),         # ◼ checked checkbox
    ("separator", "fg:#808080"),      # separator
    ("instruction", "fg:#808080"),    # hint / instruction text
    ("text", "fg:white"),             # normal text
])


# ── WizardUI class ─────────────────────────────────────────────────────────────

class WizardUI:
    """Thin wrapper producing the OpenClaw-style vertical-rail terminal UX."""

    def __init__(self, interactive: bool = True) -> None:
        self.interactive = interactive
        self._console = Console(highlight=False)

    # ── Rail output ───────────────────────────────────────────────────────────

    def rail(self, text: str = "") -> None:
        self._console.print(f"│  {text}", markup=True)

    def rail_blank(self) -> None:
        self._console.print("│")

    def section_header(self, title: str, lines: list[str]) -> None:
        """Print a boxed info panel matching the OpenClaw ◇ style."""
        width = 63
        pad = width - len(title) - 3
        self._console.print(f"◇  {title} " + "─" * max(pad, 1) + "╮")
        for line in lines:
            safe = line.replace("[", "\\[")
            self._console.print(f"│  {safe}")
        self._console.print("├" + "─" * (width + 2) + "╯")

    def success(self, text: str) -> None:
        self._console.print(f"│  [green]✓[/green] {text}")

    def warning(self, text: str) -> None:
        self._console.print(f"│  [yellow]⚠[/yellow]  {text}")

    def error(self, text: str) -> None:
        self._console.print(f"│  [red]✗[/red] {text}")

    @contextmanager
    def spinner(self, text: str) -> Generator[None, None, None]:
        """Context manager that shows a spinner (interactive) or a static line."""
        if self.interactive:
            with self._console.status(f"▪  {text} ...", spinner="dots"):
                yield
        else:
            self._console.print(f"▪  {text} ...")
            yield

    def wizard_header(self, version: str) -> None:
        self._console.print(f"┌  munAI v{version} onboarding")
        self._console.print("│")

    def wizard_footer(self) -> None:
        self._console.print("│")
        self._console.print("└  🤖 munAI is ready.")

    # ── Prompt wrappers ────────────────────────────────────────────────────────
    # In non-interactive mode every ask_* returns the given default immediately.
    # In interactive mode, None returned by questionary (Ctrl+C) raises KeyboardInterrupt.

    def ask_select(
        self,
        question: str,
        choices: list[str],
        default: str | None = None,
    ) -> str:
        if not self.interactive:
            return default if (default and default in choices) else choices[0]
        self.rail_blank()
        result = questionary.select(
            question,
            choices=choices,
            default=default,
            style=MUNAI_STYLE,
        ).ask()
        if result is None:
            raise KeyboardInterrupt
        return result

    def ask_checkbox(
        self,
        question: str,
        choices: list[str],
        defaults: list[str] | None = None,
    ) -> list[str]:
        if not self.interactive:
            return list(defaults or [])
        self.rail_blank()
        result = questionary.checkbox(
            question,
            choices=[
                questionary.Choice(c, checked=(c in (defaults or [])))
                for c in choices
            ],
            style=MUNAI_STYLE,
        ).ask()
        if result is None:
            raise KeyboardInterrupt
        return result

    def ask_text(
        self,
        question: str,
        default: str = "",
        password: bool = False,
    ) -> str:
        if not self.interactive:
            return default
        self.rail_blank()
        method = questionary.password if password else questionary.text
        result = method(question, default=default, style=MUNAI_STYLE).ask()
        if result is None:
            raise KeyboardInterrupt
        return result

    def ask_confirm(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        self.rail_blank()
        result = questionary.confirm(
            question, default=default, style=MUNAI_STYLE
        ).ask()
        if result is None:
            raise KeyboardInterrupt
        return result
