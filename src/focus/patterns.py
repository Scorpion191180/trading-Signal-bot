"""Kontextabhängige Erkennung klassischer Kerzenmuster ohne Look-ahead."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CandlePattern:
    """Ein bestätigtes Muster an der Kerze, an der es erstmals handelbar war."""

    name: str
    direction: str
    timestamp: datetime
    confidence: float
    price: float
    stop_loss: float | None
    target: float | None
    context: str
    bars: int


def _true_range(data: pd.DataFrame) -> pd.Series:
    previous_close = data["close"].shift(1)
    return pd.concat(
        (
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)


def _pattern_levels(
    data: pd.DataFrame,
    index: int,
    bars: int,
    direction: str,
    volatility: float,
) -> tuple[float, float | None, float | None]:
    start = max(index - bars + 1, 0)
    window = data.iloc[start : index + 1]
    entry = float(data["close"].iloc[index])
    buffer = max(volatility * 0.12, entry * 0.0003)
    if direction == "BULLISH":
        stop = float(window["low"].min()) - buffer
        risk = entry - stop
        return entry, stop, entry + risk * 2.0 if risk > 0 else None
    if direction == "BEARISH":
        stop = float(window["high"].max()) + buffer
        risk = stop - entry
        return entry, stop, max(entry - risk * 2.0, 0.001) if risk > 0 else None
    return entry, None, None


def scan_candlestick_patterns(
    frame: pd.DataFrame,
    *,
    lookback: int = 240,
    minimum_confidence: float = 60.0,
) -> tuple[CandlePattern, ...]:
    """Findet Muster nur mit vorangegangener Struktur und bestätigender Schlusskerze.

    Die Funktion nutzt ausschließlich Kerzen bis zum jeweiligen Zeitstempel. Dadurch
    kann dieselbe Logik im Livebetrieb und im historischen Replay verwendet werden.
    """

    required = {"open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns) or len(frame) < 6:
        return ()
    data = frame.loc[:, [*required, *( ["volume"] if "volume" in frame.columns else [])]].copy()
    for column in required | ({"volume"} if "volume" in data.columns else set()):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=list(required)).tail(max(lookback + 20, 30))
    if len(data) < 6:
        return ()

    ranges = (data["high"] - data["low"]).clip(lower=0.0)
    bodies = (data["close"] - data["open"]).abs()
    atr_values = _true_range(data).rolling(14, min_periods=5).mean()
    fallback_atr = ranges.rolling(8, min_periods=2).mean()
    atr_values = atr_values.fillna(fallback_atr).replace(0.0, np.nan)
    if "volume" in data.columns:
        volume_average = data["volume"].shift(1).rolling(20, min_periods=5).mean()
        relative_volume = data["volume"] / volume_average.replace(0.0, np.nan)
    else:
        relative_volume = pd.Series(np.nan, index=data.index)

    detected: dict[tuple[int, str], CandlePattern] = {}

    def emit(
        candle_index: int,
        name: str,
        direction: str,
        *,
        base: float,
        bars: int,
        trend_confirmed: bool,
        level_confirmed: bool,
        extra_confirmed: bool = False,
    ) -> None:
        volatility = float(atr_values.iloc[candle_index])
        if not np.isfinite(volatility) or volatility <= 0:
            volatility = max(float(ranges.iloc[candle_index]), float(data["close"].iloc[candle_index]) * 0.002)
        volume_value = float(relative_volume.iloc[candle_index])
        confidence = base
        confidence += 7.0 if trend_confirmed else 0.0
        confidence += 8.0 if level_confirmed else 0.0
        confidence += 4.0 if extra_confirmed else 0.0
        confidence += 3.0 if np.isfinite(volume_value) and volume_value >= 1.15 else 0.0
        confidence = float(np.clip(confidence, 50.0, 94.0))
        if confidence < minimum_confidence:
            return
        entry, stop, target = _pattern_levels(data, candle_index, bars, direction, volatility)
        if level_confirmed:
            level_text = "an Unterstützung" if direction == "BULLISH" else "am Widerstand"
        else:
            level_text = "mit Kerzenbestätigung"
        trend_text = "nach Abwärtstrend" if direction == "BULLISH" else "nach Aufwärtstrend"
        context = (
            f"{trend_text} · {level_text}"
            if trend_confirmed
            else level_text
        )
        pattern = CandlePattern(
            name=name,
            direction=direction,
            timestamp=pd.Timestamp(data.index[candle_index]).to_pydatetime(),
            confidence=round(confidence, 1),
            price=round(entry, 4),
            stop_loss=round(stop, 4) if stop is not None else None,
            target=round(target, 4) if target is not None else None,
            context=context,
            bars=bars,
        )
        key = (candle_index, direction)
        previous = detected.get(key)
        if previous is None or pattern.confidence > previous.confidence:
            detected[key] = pattern

    start_index = max(5, len(data) - lookback)
    for index in range(start_index, len(data)):
        current = data.iloc[index]
        previous = data.iloc[index - 1]
        before = data.iloc[index - 2]
        current_range = max(float(ranges.iloc[index]), 1e-12)
        current_body = float(bodies.iloc[index])
        body_scale = max(current_body, current_range * 0.04)
        upper_wick = float(current["high"] - max(current["open"], current["close"]))
        lower_wick = float(min(current["open"], current["close"]) - current["low"])
        previous_body = float(bodies.iloc[index - 1])
        before_body = float(bodies.iloc[index - 2])
        volatility = float(atr_values.iloc[index])
        if not np.isfinite(volatility) or volatility <= 0:
            volatility = max(current_range, float(current["close"]) * 0.002)

        prior = data.iloc[max(0, index - 14) : index]
        trend_reference = float(data["close"].iloc[max(index - 6, 0)])
        recent_close = float(previous["close"])
        downtrend = recent_close <= trend_reference - volatility * 0.30
        uptrend = recent_close >= trend_reference + volatility * 0.30
        support = float(prior["low"].min())
        resistance = float(prior["high"].max())
        near_support = float(current["low"]) <= support + volatility * 0.30
        near_resistance = float(current["high"]) >= resistance - volatility * 0.30
        bullish = float(current["close"]) > float(current["open"])
        bearish = float(current["close"]) < float(current["open"])
        previous_bullish = float(previous["close"]) > float(previous["open"])
        previous_bearish = float(previous["close"]) < float(previous["open"])
        strong_body = current_body >= current_range * 0.52

        hammer_shape = lower_wick >= body_scale * 2.0 and upper_wick <= body_scale * 0.75
        upper_rejection = upper_wick >= body_scale * 2.0 and lower_wick <= body_scale * 0.75
        if hammer_shape and (downtrend or near_support):
            emit(index, "Hammer", "BULLISH", base=61, bars=1, trend_confirmed=downtrend, level_confirmed=near_support)
        if upper_rejection and (downtrend or near_support):
            emit(index, "Invertierter Hammer", "BULLISH", base=58, bars=1, trend_confirmed=downtrend, level_confirmed=near_support)
        if upper_rejection and (uptrend or near_resistance):
            emit(index, "Shooting Star", "BEARISH", base=62, bars=1, trend_confirmed=uptrend, level_confirmed=near_resistance)
        if hammer_shape and (uptrend or near_resistance):
            emit(index, "Hanging Man", "BEARISH", base=58, bars=1, trend_confirmed=uptrend, level_confirmed=near_resistance)

        bullish_engulfing = (
            bullish
            and previous_bearish
            and float(current["open"]) <= float(previous["close"]) + volatility * 0.08
            and float(current["close"]) >= float(previous["open"]) - volatility * 0.04
            and current_body >= previous_body * 0.85
        )
        bearish_engulfing = (
            bearish
            and previous_bullish
            and float(current["open"]) >= float(previous["close"]) - volatility * 0.08
            and float(current["close"]) <= float(previous["open"]) + volatility * 0.04
            and current_body >= previous_body * 0.85
        )
        if bullish_engulfing and (downtrend or near_support):
            emit(index, "Bullish Engulfing", "BULLISH", base=66, bars=2, trend_confirmed=downtrend, level_confirmed=near_support, extra_confirmed=strong_body)
        if bearish_engulfing and (uptrend or near_resistance):
            emit(index, "Bearish Engulfing", "BEARISH", base=66, bars=2, trend_confirmed=uptrend, level_confirmed=near_resistance, extra_confirmed=strong_body)

        previous_midpoint = (float(previous["open"]) + float(previous["close"])) / 2
        piercing = (
            previous_bearish
            and bullish
            and float(current["open"]) <= float(previous["close"]) + volatility * 0.15
            and float(current["close"]) > previous_midpoint
            and float(current["close"]) <= float(previous["open"]) + volatility * 0.10
        )
        dark_cloud = (
            previous_bullish
            and bearish
            and float(current["open"]) >= float(previous["close"]) - volatility * 0.15
            and float(current["close"]) < previous_midpoint
            and float(current["close"]) >= float(previous["open"]) - volatility * 0.10
        )
        if piercing and (downtrend or near_support):
            emit(index, "Piercing Pattern", "BULLISH", base=64, bars=2, trend_confirmed=downtrend, level_confirmed=near_support)
        if dark_cloud and (uptrend or near_resistance):
            emit(index, "Dark Cloud Cover", "BEARISH", base=64, bars=2, trend_confirmed=uptrend, level_confirmed=near_resistance)

        inside_previous_body = (
            max(float(current["open"]), float(current["close"]))
            < max(float(previous["open"]), float(previous["close"]))
            and min(float(current["open"]), float(current["close"]))
            > min(float(previous["open"]), float(previous["close"]))
            and previous_body >= current_body * 1.4
        )
        if inside_previous_body and bullish and previous_bearish and (downtrend or near_support):
            emit(index, "Bullish Harami", "BULLISH", base=61, bars=2, trend_confirmed=downtrend, level_confirmed=near_support)
        if inside_previous_body and bearish and previous_bullish and (uptrend or near_resistance):
            emit(index, "Bearish Harami", "BEARISH", base=61, bars=2, trend_confirmed=uptrend, level_confirmed=near_resistance)

        same_low = abs(float(current["low"]) - float(previous["low"])) <= volatility * 0.16
        same_high = abs(float(current["high"]) - float(previous["high"])) <= volatility * 0.16
        if same_low and previous_bearish and bullish and (downtrend or near_support):
            emit(index, "Tweezer Bottom", "BULLISH", base=62, bars=2, trend_confirmed=downtrend, level_confirmed=near_support)
        if same_high and previous_bullish and bearish and (uptrend or near_resistance):
            emit(index, "Tweezer Top", "BEARISH", base=62, bars=2, trend_confirmed=uptrend, level_confirmed=near_resistance)

        before_bearish = float(before["close"]) < float(before["open"])
        before_bullish = float(before["close"]) > float(before["open"])
        middle_small = previous_body <= max(before_body, current_body) * 0.45
        morning_star = (
            before_bearish
            and middle_small
            and bullish
            and float(current["close"]) > (float(before["open"]) + float(before["close"])) / 2
        )
        evening_star = (
            before_bullish
            and middle_small
            and bearish
            and float(current["close"]) < (float(before["open"]) + float(before["close"])) / 2
        )
        if morning_star and (downtrend or near_support):
            emit(index, "Morning Star", "BULLISH", base=70, bars=3, trend_confirmed=downtrend, level_confirmed=near_support, extra_confirmed=strong_body)
        if evening_star and (uptrend or near_resistance):
            emit(index, "Evening Star", "BEARISH", base=70, bars=3, trend_confirmed=uptrend, level_confirmed=near_resistance, extra_confirmed=strong_body)

        last_three = data.iloc[index - 2 : index + 1]
        three_bullish = bool((last_three["close"] > last_three["open"]).all())
        three_bearish = bool((last_three["close"] < last_three["open"]).all())
        rising_closes = bool(np.all(np.diff(last_three["close"].to_numpy(dtype=float)) > 0))
        falling_closes = bool(np.all(np.diff(last_three["close"].to_numpy(dtype=float)) < 0))
        solid_bodies = bool(
            (
                (last_three["close"] - last_three["open"]).abs()
                >= (last_three["high"] - last_three["low"]) * 0.48
            ).all()
        )
        prior_to_three = data.iloc[max(index - 8, 0)]
        soldiers_after_weakness = float(before["close"]) <= float(prior_to_three["close"]) + volatility * 0.2
        crows_after_strength = float(before["close"]) >= float(prior_to_three["close"]) - volatility * 0.2
        if three_bullish and rising_closes and solid_bodies:
            emit(index, "Three White Soldiers", "BULLISH", base=69, bars=3, trend_confirmed=soldiers_after_weakness, level_confirmed=near_support, extra_confirmed=True)
        if three_bearish and falling_closes and solid_bodies:
            emit(index, "Three Black Crows", "BEARISH", base=69, bars=3, trend_confirmed=crows_after_strength, level_confirmed=near_resistance, extra_confirmed=True)

        inside_bar = (
            float(previous["high"]) < float(before["high"])
            and float(previous["low"]) > float(before["low"])
        )
        if inside_bar and bullish and float(current["close"]) > float(before["high"]):
            emit(index, "Inside-Bar-Ausbruch", "BULLISH", base=68, bars=3, trend_confirmed=not downtrend, level_confirmed=True, extra_confirmed=strong_body)
        if inside_bar and bearish and float(current["close"]) < float(before["low"]):
            emit(index, "Inside-Bar-Ausbruch", "BEARISH", base=68, bars=3, trend_confirmed=not uptrend, level_confirmed=True, extra_confirmed=strong_body)

        doji = current_body <= current_range * 0.10
        spinning_top = current_body <= current_range * 0.28 and upper_wick >= body_scale and lower_wick >= body_scale
        if (doji or spinning_top) and (near_support or near_resistance):
            emit(
                index,
                "Doji" if doji else "Spinning Top",
                "NEUTRAL",
                base=58,
                bars=1,
                trend_confirmed=uptrend or downtrend,
                level_confirmed=near_support or near_resistance,
            )

    return tuple(
        sorted(
            detected.values(),
            key=lambda item: (pd.Timestamp(item.timestamp), item.confidence),
        )
    )


def latest_candlestick_patterns(
    frame: pd.DataFrame,
    *,
    recent_bars: int = 3,
    minimum_confidence: float = 60.0,
) -> tuple[CandlePattern, ...]:
    patterns = scan_candlestick_patterns(
        frame,
        lookback=max(32, recent_bars + 16),
        minimum_confidence=minimum_confidence,
    )
    if not patterns or frame.empty:
        return ()
    cutoff_index = max(len(frame) - recent_bars, 0)
    cutoff = pd.Timestamp(frame.index[cutoff_index])
    return tuple(item for item in patterns if pd.Timestamp(item.timestamp) >= cutoff)


def candlestick_pattern_score(patterns: tuple[CandlePattern, ...]) -> float:
    """Verdichtet die jüngsten Muster zu einem symmetrischen Ensemble-Score."""

    bullish = max((item.confidence for item in patterns if item.direction == "BULLISH"), default=50.0)
    bearish = max((item.confidence for item in patterns if item.direction == "BEARISH"), default=50.0)
    score = 50.0 + (bullish - 50.0) * 0.72 - (bearish - 50.0) * 0.72
    return float(np.clip(score, 0.0, 100.0))
