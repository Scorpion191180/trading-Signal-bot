from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from src.focus.display import PERIOD_LABELS, PERIOD_OPTIONS, select_display_candles


def _candles(index: pd.DatetimeIndex) -> pd.DataFrame:
    values = pd.Series(range(len(index)), index=index, dtype=float) / 100 + 10
    return pd.DataFrame(
        {
            "open": values.shift(1).fillna(values.iloc[0]),
            "high": values + 0.03,
            "low": values - 0.03,
            "close": values,
            "volume": 100.0,
        },
        index=index,
    )


def test_display_periods_use_real_source_resolution_and_cutoff():
    latest = pd.Timestamp("2026-08-12 18:00", tz="UTC")
    frames = {
        "1m": _candles(pd.date_range(end=latest, periods=7 * 60, freq="1min")),
        "5m": _candles(pd.date_range(end=latest, periods=31 * 24 * 12, freq="5min")),
        "1h": _candles(pd.date_range(end=latest, periods=184 * 24, freq="1h")),
        "1d": _candles(pd.date_range(end=latest, periods=12 * 366, freq="1D")),
    }

    week = select_display_candles(frames, frames["1m"], period="1W", interval_minutes=15)
    six_months = select_display_candles(frames, frames["1m"], period="6M", interval_minutes=1440)
    three_years = select_display_candles(frames, frames["1m"], period="3J", interval_minutes=10080)

    assert len(week) > 0
    assert week.index[-1] - week.index[0] <= timedelta(days=7, minutes=15)
    assert six_months.index[-1] - six_months.index[0] <= timedelta(days=184)
    assert 145 <= len(three_years) <= 160
    assert three_years.index[-1] <= frames["1d"].index[-1]


def test_intraday_interval_and_invalid_period_interval():
    live = _candles(pd.date_range("2026-08-12 05:30", periods=180, freq="1min", tz="UTC"))

    five_minutes = select_display_candles({}, live, period="Intraday", interval_minutes=5)

    assert 35 <= len(five_minutes) <= 37
    with pytest.raises(ValueError, match="passt nicht"):
        select_display_candles({}, live, period="6M", interval_minutes=1)


def test_period_labels_make_day_month_and_year_views_explicit():
    assert PERIOD_OPTIONS[0] == "Intraday"
    assert PERIOD_LABELS["Intraday"] == "Heute"
    assert PERIOD_LABELS["1M"] == "1 Monat"
    assert PERIOD_LABELS["1J"] == "1 Jahr"
    assert PERIOD_LABELS["Max"] == "Gesamte Historie"
