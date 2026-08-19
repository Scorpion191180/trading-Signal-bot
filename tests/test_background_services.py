from __future__ import annotations

from pathlib import Path

from scripts.install_background_bot import BOT_LABEL, WEB_LABEL, service_payloads
from scripts.run_web_service import streamlit_command


def test_launch_agents_keep_web_app_and_bot_alive(tmp_path: Path):
    repository = tmp_path / "trading-Signal-bot"
    payloads = service_payloads(repository)

    assert set(payloads) == {BOT_LABEL, WEB_LABEL}
    assert all(payload["RunAtLoad"] is True for payload in payloads.values())
    assert all(payload["KeepAlive"] is True for payload in payloads.values())
    assert payloads[BOT_LABEL]["ProgramArguments"][-2:] == ["-m", "src.focus.worker"]
    assert payloads[WEB_LABEL]["ProgramArguments"][-2:] == ["-m", "scripts.run_web_service"]
    assert payloads[WEB_LABEL]["EnvironmentVariables"]["TRADING_SIGNAL_WEB_PORT"] == "8502"


def test_web_supervisor_uses_local_streamlit_on_port_8502(tmp_path: Path):
    command = streamlit_command(tmp_path, 8502)

    assert command[:3] == [str(tmp_path / ".venv" / "bin" / "python"), "-m", "streamlit"]
    assert command[3:5] == ["run", str(tmp_path / "app.py")]
    assert command[command.index("--server.port") + 1] == "8502"
    assert command[command.index("--server.address") + 1] == "0.0.0.0"
