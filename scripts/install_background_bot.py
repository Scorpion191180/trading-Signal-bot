"""Installiert Web-App und Papier-Bot als persönliche macOS-LaunchAgents."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

BOT_LABEL = "com.trading-signal-bot.dwave-paper"
WEB_LABEL = "com.trading-signal-bot.web"


def service_payloads(repository: Path) -> dict[str, dict[str, object]]:
    interpreter = repository / ".venv" / "bin" / "python"
    data_directory = repository / "data"
    database_path = data_directory / "trading_signal_live.db"
    shared_environment = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "PYTHONUNBUFFERED": "1",
    }
    shared: dict[str, object] = {
        "WorkingDirectory": str(repository),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "EnvironmentVariables": shared_environment,
    }
    return {
        BOT_LABEL: {
            **shared,
            "Label": BOT_LABEL,
            "ProgramArguments": [str(interpreter), "-m", "src.focus.worker"],
            "StandardOutPath": str(data_directory / "dwave-paper-bot.log"),
            "StandardErrorPath": str(data_directory / "dwave-paper-bot.error.log"),
        },
        WEB_LABEL: {
            **shared,
            "Label": WEB_LABEL,
            "ProgramArguments": [str(interpreter), "-m", "scripts.run_web_service"],
            "EnvironmentVariables": {
                **shared_environment,
                "TRADING_SIGNAL_WEB_PORT": "8502",
            },
            "StandardOutPath": str(data_directory / "web-app.log"),
            "StandardErrorPath": str(data_directory / "web-app.error.log"),
        },
    }


def install_service(
    *,
    domain: str,
    launch_agents: Path,
    label: str,
    payload: dict[str, object],
) -> Path:
    plist_path = launch_agents / f"{label}.plist"
    temporary_path = plist_path.with_suffix(".plist.tmp")
    with temporary_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    temporary_path.replace(plist_path)

    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=False, capture_output=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=False, capture_output=True)
    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if bootstrap.returncode:
        details = bootstrap.stderr.strip() or bootstrap.stdout.strip()
        raise RuntimeError(f"{label} konnte nicht geladen werden: {details}")
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=True)
    return plist_path


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    interpreter = repository / ".venv" / "bin" / "python"
    if not interpreter.is_file():
        raise SystemExit(f"Python-Umgebung fehlt: {interpreter}")

    (repository / "data").mkdir(parents=True, exist_ok=True)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    installed: list[Path] = []
    failures: list[str] = []
    for label, payload in service_payloads(repository).items():
        try:
            installed.append(
                install_service(
                    domain=domain,
                    launch_agents=launch_agents,
                    label=label,
                    payload=payload,
                )
            )
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            failures.append(str(exc))
    if failures:
        raise SystemExit(
            "Die Dienstdateien wurden angelegt, aber nicht vollständig gestartet. "
            "Bitte dieses Installationsskript einmal direkt im macOS-Terminal ausführen. "
            + " | ".join(failures)
        )
    for path in installed:
        print(path)
    print("Web-App: http://localhost:8502/")


if __name__ == "__main__":
    main()
