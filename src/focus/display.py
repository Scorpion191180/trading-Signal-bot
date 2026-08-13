"""Zeitraum- und Intervallauswahl für die professionelle Chartansicht."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .data import resample_ohlcv
from .quote import resample_intraday_candles

PERIOD_OPTIONS = ("Max", "Intraday", "1W", "1M", "3M", "6M", "1J", "3J", "5J", "10J", "YTD")
PERIOD_INTERVALS = {
    "Intraday": (1, 5, 15, 30, 60, 120, 300),
    "1W": (1, 5, 15, 30, 60, 1440),
    "1M": (5, 15, 30, 60, 1440),
    "3M": (60, 1440),
    "6M": (60, 1440),
    "1J": (1440, 10080),
    "3J": (1440, 10080, 43200),
    "5J": (1440, 10080, 43200),
    "10J": (1440, 10080, 43200),
    "YTD": (1440, 10080),
    "Max": (1440, 10080, 43200),
}
DISPLAY_INTERVAL_LABELS = {
    1: "1 Min",
    5: "5 Min",
    15: "15 Min",
    30: "30 Min",
    60: "1 Std",
    120: "2 Std",
    300: "5 Std",
    1440: "1 Tag",
    10080: "1 Woche",
    43200: "1 Monat",
}
DEFAULT_INTERVAL = {
    "Intraday": 5,
    "1W": 15,
    "1M": 60,
    "3M": 1440,
    "6M": 1440,
    "1J": 1440,
    "3J": 10080,
    "5J": 10080,
    "10J": 43200,
    "YTD": 1440,
    "Max": 43200,
}


def _period_cutoff(index: pd.DatetimeIndex, period: str) -> pd.Timestamp | None:
    latest = index[-1]
    days = {"1W": 7, "1M": 31, "3M": 92, "6M": 184, "1J": 366, "3J": 1096, "5J": 1827, "10J": 3653}
    if period in days:
        return latest - timedelta(days=days[period])
    if period == "YTD":
        local_latest = latest.tz_convert("Europe/Berlin")
        return pd.Timestamp(year=local_latest.year, month=1, day=1, tz="Europe/Berlin").tz_convert(latest.tz)
    return None


def _slice_period(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if frame.empty or period in {"Max", "Intraday"}:
        return frame
    cutoff = _period_cutoff(frame.index, period)
    return frame.loc[frame.index >= cutoff].copy() if cutoff is not None else frame


def select_display_candles(
    frames: dict[str, pd.DataFrame],
    live_candles: pd.DataFrame,
    *,
    period: str,
    interval_minutes: int,
) -> pd.DataFrame:
    """Wählt die feinste echte Quellreihe und verdichtet sie ohne künstliches Hochskalieren."""

    if period not in PERIOD_INTERVALS:
        raise ValueError("Der Chartzeitraum wird nicht unterstützt.")
    if interval_minutes not in PERIOD_INTERVALS[period]:
        raise ValueError("Das Kerzenintervall passt nicht zum gewählten Zeitraum.")
    if period == "Intraday":
        result = resample_intraday_candles(live_candles, interval_minutes)
        result.attrs.update(live_candles.attrs)
        return result

    if interval_minutes == 1:
        source = frames.get("1m")
    elif interval_minutes < 60:
        source = frames.get("5m")
    elif interval_minutes < 1440:
        source = frames.get("1h")
    else:
        source = frames.get("1d")
    if source is None or source.empty:
        raise ValueError("Für diesen Zeitraum sind gerade keine historischen Kerzen verfügbar.")

    if interval_minutes == 1 or (interval_minutes == 5 and period != "Intraday"):
        result = source.copy()
    elif interval_minutes < 1440:
        result = resample_intraday_candles(source, interval_minutes)
    elif interval_minutes == 1440:
        result = source.copy()
    elif interval_minutes == 10080:
        result = resample_ohlcv(source, "W-FRI", drop_future_label=True)
    else:
        result = resample_ohlcv(source, "ME", drop_future_label=True)
    result = _slice_period(result, period)
    result.attrs.update(source.attrs)
    if result.empty:
        raise ValueError("Im gewählten Zeitraum liegen keine Kerzen vor.")
    return result
