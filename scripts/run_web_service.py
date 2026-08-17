"""Hält die lokale Streamlit-App unabhängig von Codex dauerhaft erreichbar."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from pathlib import Path
from time import monotonic
from urllib.error import URLError
from urllib.request import urlopen

CHECK_INTERVAL_SECONDS = 5
STARTUP_GRACE_SECONDS = 45
MAX_HEALTH_FAILURES = 3


def streamlit_command(repository: Path, port: int) -> list[str]:
    return [
        str(repository / ".venv" / "bin" / "python"),
        "-m",
        "streamlit",
        "run",
        str(repository / "app.py"),
        "--server.address",
        "0.0.0.0",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]


def is_healthy(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3) as response:  # noqa: S310
            return response.status == 200 and response.read().strip() == b"ok"
    except (OSError, URLError):
        return False


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def supervise(repository: Path, port: int, stop_event: threading.Event) -> None:
    """Startet Streamlit neu, wenn Prozess oder Gesundheitsprüfung ausfallen."""

    while not stop_event.is_set():
        process = subprocess.Popen(streamlit_command(repository, port), cwd=repository)  # noqa: S603
        started_at = monotonic()
        failed_checks = 0
        while process.poll() is None and not stop_event.wait(CHECK_INTERVAL_SECONDS):
            if monotonic() - started_at < STARTUP_GRACE_SECONDS:
                continue
            if is_healthy(port):
                failed_checks = 0
                continue
            failed_checks += 1
            if failed_checks >= MAX_HEALTH_FAILURES:
                stop_process(process)
                break
        if stop_event.is_set():
            stop_process(process)
            return
        stop_event.wait(CHECK_INTERVAL_SECONDS)


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    port = int(os.getenv("TRADING_SIGNAL_WEB_PORT", "8502"))
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    supervise(repository, port, stop_event)


if __name__ == "__main__":
    main()
