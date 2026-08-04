"""Vorsichtige Erkennung einfacher Unterstützungs- und Widerstandszonen."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PriceZone:
    kind: str
    lower: float
    upper: float
    touches: int

    @property
    def middle(self) -> float:
        return (self.lower + self.upper) / 2


def detect_zones(data: pd.DataFrame, window: int = 5, tolerance_pct: float = 0.006) -> list[PriceZone]:
    """Bündelt lokale Hochs/Tiefs zu Zonen; bewusst keine vermeintliche Präzisionslinie."""

    if len(data) < (window * 2 + 1):
        return []
    lows = data["low"][(data["low"] == data["low"].rolling(window * 2 + 1, center=True).min())]
    highs = data["high"][(data["high"] == data["high"].rolling(window * 2 + 1, center=True).max())]
    current = float(data["close"].iloc[-1])
    candidates = [("Unterstützung", float(value)) for value in lows.dropna()]
    candidates += [("Widerstand", float(value)) for value in highs.dropna()]
    zones: list[PriceZone] = []
    for kind, price in candidates[-40:]:
        matching_index = next(
            (
                index
                for index, zone in enumerate(zones)
                if zone.kind == kind and abs(zone.middle - price) / max(price, 1e-9) <= tolerance_pct
            ),
            None,
        )
        half_width = max(price * tolerance_pct / 2, 1e-6)
        if matching_index is None:
            zones.append(PriceZone(kind, price - half_width, price + half_width, 1))
        else:
            old = zones[matching_index]
            midpoint = np.mean([old.middle] * old.touches + [price])
            zones[matching_index] = PriceZone(
                kind,
                float(midpoint - half_width),
                float(midpoint + half_width),
                old.touches + 1,
            )
    relevant = [
        zone
        for zone in zones
        if (zone.kind == "Unterstützung" and zone.middle <= current * 1.03)
        or (zone.kind == "Widerstand" and zone.middle >= current * 0.97)
    ]
    return sorted(relevant, key=lambda zone: (abs(zone.middle - current), -zone.touches))[:6]


def nearest_levels(data: pd.DataFrame) -> tuple[float | None, float | None, list[PriceZone]]:
    zones = detect_zones(data)
    current = float(data["close"].iloc[-1])
    supports = [zone.middle for zone in zones if zone.kind == "Unterstützung" and zone.middle < current]
    resistances = [zone.middle for zone in zones if zone.kind == "Widerstand" and zone.middle > current]
    return (max(supports, default=None), min(resistances, default=None), zones)
