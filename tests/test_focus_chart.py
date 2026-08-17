from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.focus.analysis import FocusPosition, IntradaySignal, TrendForecast
from src.focus.charts import _trading_minute_target, day_signal_chart
from src.focus.quote import LiveQuote


def test_forecast_target_skips_closed_market_and_weekend():
    friday = pd.Timestamp("2026-08-14 22:30", tz="Europe/Berlin")

    assert _trading_minute_target(friday, 60) == pd.Timestamp(
        "2026-08-17 08:00",
        tz="Europe/Berlin",
    )
    assert _trading_minute_target(friday, 120) == pd.Timestamp(
        "2026-08-17 09:00",
        tz="Europe/Berlin",
    )


def test_day_signal_chart_contains_live_price_position_and_signal():
    index = pd.date_range("2026-08-12 08:00", periods=40, freq="1min", tz="UTC")
    values = pd.Series(range(40), index=index, dtype=float) / 100 + 17
    candles = pd.DataFrame(
        {
            "open": values.shift(1).fillna(values.iloc[0]),
            "high": values + 0.02,
            "low": values - 0.02,
            "close": values,
            "volume": 100.0,
        },
        index=index,
    )
    quote = LiveQuote(
        provider="Tradegate BSX Level 1",
        venue="Tradegate BSX",
        isin="US26740W1099",
        bid=17.38,
        ask=17.40,
        bid_size=5000,
        ask_size=5000,
        last=17.39,
        high=17.45,
        low=16.95,
        change_percent=1.0,
        volume=10000,
        fetched_at=datetime(2026, 8, 12, 8, 40, tzinfo=UTC),
        refresh_seconds=10,
    )
    signal = IntradaySignal(
        action="HOLD",
        headline="HALTEN / BEOBACHTEN",
        score=60,
        strength="schwach",
        color="#64748b",
        current_price=17.39,
        entry_low=None,
        entry_high=None,
        stop_loss=17.20,
        target=17.60,
        holding_period="5–30 Minuten",
        reasons=(),
        warning="Beobachten",
        data_age_minutes=0,
        market_open=True,
    )

    figure = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(invested=True, average_price=17.1, quantity=10),
        [],
    )

    assert len(figure.data) == 2
    assert len(figure.data[0].open) == 8
    assert figure.data[0].high[0] > max(figure.data[0].open[0], figure.data[0].close[0])
    assert figure.data[0].low[0] < min(figure.data[0].open[0], figure.data[0].close[0])
    assert figure.data[0].whiskerwidth == 0.65
    assert figure.data[1].name == "L&S Bid"
    assert figure.data[1].y[0] == quote.bid
    assert any("HALTEN" in annotation.text for annotation in figure.layout.annotations)
    assert figure.layout.uirevision == "dwave-professional-Intraday-5-Kerzen"
    assert figure.layout.dragmode == "pan"
    assert figure.layout.xaxis.showspikes
    assert figure.layout.yaxis.side == "right"
    assert any("Einstand" in annotation.text for annotation in figure.layout.annotations)
    assert any("Investiert 171.00 €" in annotation.text for annotation in figure.layout.annotations)
    assert any("Verkaufswert 173.80 €" in annotation.text for annotation in figure.layout.annotations)
    assert any("Plus/Minus +2.80 €" in annotation.text for annotation in figure.layout.annotations)
    assert len(figure.layout.shapes) >= 3

    hour_figure = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(invested=True, average_price=17.1, quantity=10),
        [],
        candle_minutes=60,
    )
    assert hour_figure.data[0].name == "1-Stunde-Kerzen"
    assert hour_figure.layout.xaxis.title.text == ""
    assert hour_figure.layout.uirevision == "dwave-professional-Intraday-60-Kerzen"

    quiet_minutes = candles.reindex(
        pd.date_range(candles.index[0], periods=240, freq="1min", tz="UTC")
    ).ffill()
    quiet_minutes["volume"] = 0.0
    quiet_minutes.iloc[::60, quiet_minutes.columns.get_loc("volume")] = 100.0
    minute_figure = day_signal_chart(
        quiet_minutes,
        quote,
        signal,
        FocusPosition(),
        [],
        candle_minutes=1,
    )
    assert len(minute_figure.data[0].x) == 240
    assert minute_figure.data[1].name == "Minutenverlauf"
    assert minute_figure.layout.xaxis.range is not None
    assert pd.Timestamp(minute_figure.layout.xaxis.range[0]) < quiet_minutes.index[0].tz_convert("Europe/Berlin")
    assert pd.Timestamp(minute_figure.layout.xaxis.range[1]) > quiet_minutes.index[-1].tz_convert("Europe/Berlin")
    assert minute_figure.layout.yaxis.autorange is False
    assert minute_figure.layout.xaxis.rangebreaks

    line_figure = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(),
        [],
        chart_style="Linie",
        overlays={"EMA"},
    )
    assert line_figure.data[0].name == "Kurs"
    assert [trace.name for trace in line_figure.data[1:3]] == ["EMA 8", "EMA 21"]
    assert line_figure.layout.showlegend


def test_distant_entry_does_not_flatten_the_day_chart():
    index = pd.date_range("2026-08-12 08:00", periods=40, freq="1min", tz="UTC")
    candles = pd.DataFrame(
        {
            "open": 17.0,
            "high": 17.2,
            "low": 16.9,
            "close": 17.1,
            "volume": 100.0,
        },
        index=index,
    )
    quote = LiveQuote(
        "Tradegate BSX Level 1",
        "Tradegate BSX",
        "US26740W1099",
        17.09,
        17.11,
        None,
        None,
        17.1,
        17.2,
        16.9,
        0.0,
        1000,
        datetime(2026, 8, 12, 8, 40, tzinfo=UTC),
        10,
    )
    signal = IntradaySignal(
        "NO_SIGNAL",
        "KEIN SIGNAL",
        50,
        "keine",
        "#64748b",
        17.1,
        None,
        None,
        None,
        None,
        "5–30 Minuten",
        (),
        "Warten",
        0,
        True,
    )

    figure = day_signal_chart(candles, quote, signal, FocusPosition(True, 25.0, 10), [])

    assert not any("Einstand" in annotation.text for annotation in figure.layout.annotations)


def test_historical_forecast_is_drawn_at_its_target_time():
    index = pd.date_range("2026-08-12 08:00", periods=90, freq="1min", tz="UTC")
    candles = pd.DataFrame(
        {"open": 17.0, "high": 17.2, "low": 16.9, "close": 17.1, "volume": 100.0},
        index=index,
    )
    quote = LiveQuote(
        "stock3",
        "Lang & Schwarz",
        "US26740W1099",
        17.1,
        17.12,
        None,
        None,
        17.1,
        17.2,
        16.9,
        0.0,
        None,
        datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
        10,
    )
    signal = IntradaySignal(
        "WAIT",
        "WARTEN",
        50,
        "neutral",
        "#64748b",
        17.1,
        None,
        None,
        None,
        None,
        "bis 120 Minuten",
        (),
        "",
        0,
        True,
        trend_forecasts=(
            TrendForecast(120, "STEIGEND", 17.55, 16.75, 17.85, 61.0),
        ),
    )
    target_at = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    history = [
        {
            "forecast_at": datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
            "target_at": target_at,
            "entry_price": 17.1,
            "expected_price": 17.15,
            "expected_low": 17.0,
            "expected_high": 17.3,
            "direction": "STEIGEND",
            "observed_price": 17.2,
            "direction_hit": True,
            "released": True,
        }
    ]

    figure = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(),
        [],
        historical_forecasts=history,
        forecast_horizon_minutes=60,
    )

    forecast_trace = next(trace for trace in figure.data if trace.name.startswith("Ziel nach 60 Min"))
    current_trace = next(trace for trace in figure.data if trace.name.startswith("Modelltest"))
    assert pd.Timestamp(forecast_trace.x[0]).tz_convert("UTC") == pd.Timestamp(target_at)
    assert forecast_trace.marker.color[0] == "#22c55e"
    assert "1/1 (100 %)" in forecast_trace.name
    assert forecast_trace.line.width >= 3
    assert forecast_trace.marker.size >= 6
    issued_trace = next(trace for trace in figure.data if trace.name.startswith("Erstellt"))
    assert pd.Timestamp(issued_trace.x[0]).tz_convert("UTC") == pd.Timestamp(history[0]["forecast_at"])
    assert current_trace.line.width >= 2.5
    assert current_trace.marker.size >= 8
    assert pd.Timestamp(figure.layout.xaxis.range[1]) > pd.Timestamp(current_trace.x[-1])
    assert float(figure.layout.yaxis.range[0]) < 16.75
    assert float(figure.layout.yaxis.range[1]) > 17.85

    zoomed = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(),
        [],
        axis_ranges={
            "x": ["2026-08-12T08:30:00+00:00", "2026-08-12T09:00:00+00:00"],
            "y": [17.0, 17.4],
        },
    )
    assert zoomed.layout.xaxis.autorange is False
    assert tuple(zoomed.layout.xaxis.range) == (
        "2026-08-12T08:30:00+00:00",
        "2026-08-12T09:00:00+00:00",
    )
    assert zoomed.layout.yaxis.autorange is False
    assert tuple(zoomed.layout.yaxis.range) == (17.0, 17.4)

    stale_overview = day_signal_chart(
        candles,
        quote,
        signal,
        FocusPosition(),
        [],
        axis_ranges={
            "x": [candles.index[0], candles.index[-1]],
            "y": [16.8, 18.2],
        },
    )
    assert pd.Timestamp(stale_overview.layout.xaxis.range[1]) > pd.Timestamp(current_trace.x[-1])
    assert float(stale_overview.layout.yaxis.range[0]) < 16.75
    assert float(stale_overview.layout.yaxis.range[1]) > 17.85
