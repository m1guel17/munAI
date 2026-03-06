"""Daemon installation helpers for systemd (Linux) and launchd (macOS)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .wizard_state import WizardState
    from .wizard_ui import WizardUI


# ── Executable detection ───────────────────────────────────────────────────────

def find_munai_executable() -> str:
    """Return the full path to the munai CLI binary.

    Prefers a ``munai`` entry on PATH; falls back to
    ``{sys.executable} -m munai`` for editable installs.
    """
    path = shutil.which("munai")
    if path:
        return path
    return f"{sys.executable} -m munai"


# ── systemd (Linux) ────────────────────────────────────────────────────────────

def generate_systemd_unit(munai_exe: str, env_file: Path) -> str:
    """Return the content of a systemd user unit file."""
    home = Path.home()
    return f"""\
[Unit]
Description=munAI Gateway
After=network.target

[Service]
Type=simple
ExecStart={munai_exe} gateway
Restart=on-failure
RestartSec=5
EnvironmentFile={env_file}
WorkingDirectory={home / ".munai"}

[Install]
WantedBy=default.target
"""


def install_systemd(
    munai_exe: str,
    env_file: Path,
    unit_dir: Path | None = None,
) -> None:
    """Write the unit file and enable/start the service.

    Args:
        munai_exe: Path to the munai executable.
        env_file: Path to the .env file passed as EnvironmentFile.
        unit_dir: Override the systemd user unit directory (for testing).
    """
    if unit_dir is None:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    unit_path = unit_dir / "munai-gateway.service"
    unit_path.write_text(generate_systemd_unit(munai_exe, env_file), encoding="utf-8")

    # Only attempt systemctl commands when running on a real system
    if unit_dir == Path.home() / ".config" / "systemd" / "user":
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "munai-gateway"], check=False)
        subprocess.run(["systemctl", "--user", "start", "munai-gateway"], check=False)
        subprocess.run(
            ["loginctl", "enable-linger", Path.home().name], check=False
        )


# ── launchd (macOS) ────────────────────────────────────────────────────────────

def generate_launchd_plist(munai_exe: str, env_vars: dict[str, str]) -> str:
    """Return the content of a launchd plist (XML)."""
    home = Path.home()
    env_xml = "".join(
        f"        <key>{k}</key>\n        <string>{v}</string>\n"
        for k, v in env_vars.items()
    )
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.munai.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>{munai_exe}</string>
        <string>gateway</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{home / ".munai"}</string>
    <key>EnvironmentVariables</key>
    <dict>
{env_xml}    </dict>
</dict>
</plist>
"""


def install_launchd(
    munai_exe: str,
    env_vars: dict[str, str],
    agents_dir: Path | None = None,
) -> None:
    """Write the plist and load it with launchctl.

    Args:
        munai_exe: Path to the munai executable.
        env_vars: Environment variables to embed in the plist.
        agents_dir: Override the LaunchAgents directory (for testing).
    """
    if agents_dir is None:
        agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    plist_path = agents_dir / "ai.munai.gateway.plist"
    plist_path.write_text(generate_launchd_plist(munai_exe, env_vars), encoding="utf-8")

    if agents_dir == Path.home() / "Library" / "LaunchAgents":
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)


# ── Platform dispatcher ────────────────────────────────────────────────────────

def install_daemon(state: "WizardState", ui: "WizardUI") -> bool:
    """Detect platform and install the gateway as a background service.

    Returns True on success, False on failure or unsupported platform.
    """
    munai_exe = find_munai_executable()
    env_file = Path.home() / ".munai" / ".env"

    if sys.platform.startswith("linux"):
        try:
            install_systemd(munai_exe, env_file)
            ui.success("Service installed: munai-gateway.service")
            ui.success("Service started")
            return True
        except Exception as exc:
            ui.error(f"Failed to install systemd unit: {exc}")
            return False

    elif sys.platform == "darwin":
        try:
            install_launchd(munai_exe, state.env_vars)
            ui.success("Service installed: ai.munai.gateway.plist")
            ui.success("Service started")
            return True
        except Exception as exc:
            ui.error(f"Failed to install launchd plist: {exc}")
            return False

    else:
        ui.warning(
            f"Daemon installation not supported on {sys.platform}. "
            "Use 'munai gateway' to start the gateway manually."
        )
        return False
