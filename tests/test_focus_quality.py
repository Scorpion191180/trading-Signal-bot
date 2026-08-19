from __future__ import annotations

import pandas as pd

from src.focus.analysis import IntradaySignal, TrendForecast, analyze_timeframes
from src.focus.quality import forecast_horizon_payloads


def test_every_forecast_is_visible_even_before_target_accuracy_is_reached():
    signal = IntradaySignal(
        action="WAIT",
        headline="WARTEN",
        score=51.0,
        strength="schwach",
        color="#64748b",
        current_price=17.0,
        entry_low=None,
        entry_high=None,
        stop_loss=None,
        target=None,
        holding_period="adaptiv",
        reasons=(),
        warning="",
        data_age_minutes=0.0,
        market_open=True,
        trend_forecasts=(TrendForecast(60, "STEIGEND", 17.1, 16.9, 17.3, 52.0),),
    )

    payload = forecast_horizon_payloads(
        signal,
        {60: {"qualified": False, "total": 10, "raw_accuracy": 40.0}},
    )[0]

    assert payload["released"] is True
    assert "Immer sichtbare Prognose" in str(payload["release_reason"])


def test_short_long_term_history_can_be_kept_as_neutral_comparison_context():
    index = pd.date_range("2026-06-30", periods=3, freq="ME", tz="UTC")
    values = pd.Series([30.0 + offset * 0.1 for offset in range(3)], index=index)
    monthly = pd.DataFrame(
        {
            "open": values - 0.05,
            "high": values + 0.1,
            "low": values - 0.1,
            "close": values,
            "volume": 0.0,
        },
        index=index,
    )

    analyses, enriched, errors = analyze_timeframes(
        {"1mo": monthly},
        allow_neutral_long_term_context=True,
    )

    assert "1mo" not in errors
    assert analyses["1mo"].score == 50.0
    assert analyses["1mo"].trend == "Seitwärts"
    assert len(enriched["1mo"]) == len(monthly)
    assert {"atr_14", "ema_fast", "ema_slow"}.issubset(enriched["1mo"].columns)
