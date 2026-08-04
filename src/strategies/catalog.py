"""Serialisierbare Strategiedefinitionen für UI und Persistenz."""

from __future__ import annotations

from dataclasses import asdict

from src.config import STRATEGIES


def strategy_rows() -> list[dict[str, object]]:
    return [asdict(profile) for profile in STRATEGIES.values()]
