"""Installiert den Papier-Bot als persönlichen macOS-LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.trading-signal-bot.dwave-paper"


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    interpreter = repository / ".venv" / "bin" / "python"
    if not interpreter.is_file():
        raise SystemExit(f"Python-Umgebung fehlt: {interpreter}")

    data_directory = repository / "data"
    data_directory.mkdir(parents=True, exist_ok=True)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{LABEL}.plist"
    database_path = data_directory / "trading_signal_live.db"
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(interpreter), "-m", "src.focus.worker"],
        "WorkingDirectory": str(repository),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "EnvironmentVariables": {
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(data_directory / "dwave-paper-bot.log"),
        "StandardErrorPath": str(data_directory / "dwave-paper-bot.error.log"),
    }
    temporary_path = plist_path.with_suffix(".plist.tmp")
    with temporary_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    temporary_path.replace(plist_path)

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=False, capture_output=True)
    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if bootstrap.returncode:
        details = bootstrap.stderr.strip() or bootstrap.stdout.strip()
        raise SystemExit(
            f"Die Dienstdatei wurde unter {plist_path} installiert, konnte aber nicht sofort geladen werden. "
            f"Bitte das Installationsskript einmal direkt im macOS-Terminal starten. {details}"
        )
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
    print(plist_path)


if __name__ == "__main__":
    main()
