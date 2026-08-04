"""Nachvollziehbare technische Indikatoren ohne versteckte Anbieterlogik."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.base import normalize_ohlcv


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + relative_strength))
    result = result.mask((average_loss == 0) & (average_gain > 0), 100.0)
    return result.mask((average_loss == 0) & (average_gain == 0), 50.0)


def true_range(data: pd.DataFrame) -> pd.Series:
    previous_close = data["close"].shift(1)
    return pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(data).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt die für Version 0.1 vereinbarten technischen Kennzahlen."""

    data = normalize_ohlcv(frame)
    for period in (20, 50, 200):
        data[f"ema_{period}"] = ema(data["close"], period)
    data["rsi_14"] = rsi(data["close"], 14)
    data["macd"] = ema(data["close"], 12) - ema(data["close"], 26)
    data["macd_signal"] = ema(data["macd"], 9)
    data["macd_hist"] = data["macd"] - data["macd_signal"]
    data["atr_14"] = atr(data, 14)
    middle = data["close"].rolling(20, min_periods=20).mean()
    deviation = data["close"].rolling(20, min_periods=20).std(ddof=0)
    data["bb_middle"] = middle
    data["bb_upper"] = middle + (2 * deviation)
    data["bb_lower"] = middle - (2 * deviation)
    data["bb_width"] = (data["bb_upper"] - data["bb_lower"]) / middle.replace(0.0, np.nan)
    typical_price = (data["high"] + data["low"] + data["close"]) / 3
    session = data.index.tz_convert("UTC").date
    cumulative_value = (typical_price * data["volume"]).groupby(session).cumsum()
    cumulative_volume = data["volume"].groupby(session).cumsum().replace(0.0, np.nan)
    data["vwap"] = cumulative_value / cumulative_volume
    average_volume = data["volume"].shift(1).rolling(20, min_periods=5).mean()
    data["relative_volume"] = data["volume"] / average_volume.replace(0.0, np.nan)
    data["obv"] = (np.sign(data["close"].diff()).fillna(0) * data["volume"]).cumsum()
    return data
