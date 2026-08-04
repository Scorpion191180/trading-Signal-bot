"""Einfache kontextbezogene Candlestick-Merkmale für das MVP."""

from __future__ import annotations

import pandas as pd


def candlestick_context(data: pd.DataFrame) -> tuple[float, list[str], list[str]]:
    """Bewertet robuste Einzelkerzenmerkmale und gibt einen Faktor von 0 bis 1 zurück."""

    if len(data) < 3:
        return 0.5, [], ["Zu wenige Kerzen für Musterbewertung"]
    current = data.iloc[-1]
    previous = data.iloc[-2]
    candle_range = max(float(current["high"] - current["low"]), 1e-9)
    body = abs(float(current["close"] - current["open"]))
    upper_wick = float(current["high"] - max(current["open"], current["close"]))
    lower_wick = float(min(current["open"], current["close"]) - current["low"])
    positive: list[str] = []
    negative: list[str] = []
    factor = 0.5
    if body / candle_range < 0.1:
        negative.append("Doji: kurzfristige Unentschlossenheit")
    if lower_wick > body * 2 and float(current["close"]) >= float(current["open"]):
        factor += 0.18
        positive.append("Langer unterer Docht/Hammer")
    if upper_wick > body * 2 and float(current["close"]) <= float(current["open"]):
        factor -= 0.18
        negative.append("Langer oberer Docht/Shooting Star")
    bullish_engulfing = (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["open"] <= previous["close"]
        and current["close"] >= previous["open"]
    )
    bearish_engulfing = (
        previous["close"] > previous["open"]
        and current["close"] < current["open"]
        and current["open"] >= previous["close"]
        and current["close"] <= previous["open"]
    )
    if bullish_engulfing:
        factor += 0.22
        positive.append("Bullish Engulfing")
    if bearish_engulfing:
        factor -= 0.22
        negative.append("Bearish Engulfing")
    return min(max(factor, 0.0), 1.0), positive, negative
