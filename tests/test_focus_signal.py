from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from src.data import MarketDataRequest
from src.focus.analysis import FocusPosition, analyze_timeframes, build_intraday_signal
from src.focus.data import load_dwave_timeframes, resample_ohlcv

FREQUENCIES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "1d": "1D",
    "1wk": "7D",
    "1mo": "30D",
}
FREQUENCY_DURATIONS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1wk": timedelta(days=7),
    "1mo": timedelta(days=30),
}


def _frames(now: datetime, *, bearish: bool = False) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for offset, (key, frequency) in enumerate(FREQUENCIES.items()):
        rows = 360
        duration = FREQUENCY_DURATIONS[key]
        index = pd.date_range(end=pd.Timestamp(now) - duration, periods=rows, freq=frequency, tz="UTC")
        generator = np.random.default_rng(12 + offset)
        if bearish:
            close = 20 - np.arange(rows) * 0.008 + np.sin(np.arange(rows) / 3) * 0.03
            close += generator.normal(0, 0.005, rows)
            close[-30:] -= np.arange(30) * 0.02
        else:
            close = 10 + np.arange(rows) * 0.003 + np.sin(np.arange(rows) / 3) * 0.08
            close += generator.normal(0, 0.015, rows)
        open_ = np.concatenate(([close[0]], close[:-1]))
        frames[key] = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) + 0.04,
                "low": np.minimum(open_, close) - 0.04,
                "close": close,
                "volume": generator.integers(900, 1600, rows),
            },
            index=index,
        )
    return frames


def test_short_term_confirmation_creates_buy_and_profitable_add_signal():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, errors = analyze_timeframes(_frames(now))
    assert errors == {}

    buy = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        enforce_market_hours=False,
    )
    add = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(invested=True, average_price=10.0, quantity=5),
        now=now,
        enforce_market_hours=False,
    )

    assert buy.action == "BUY"
    assert add.action == "ADD"
    assert buy.holding_period == "5–30 Minuten"
    assert buy.entry_low < buy.current_price < buy.entry_high
    assert buy.stop_loss < buy.current_price < buy.target


def test_add_signal_does_not_average_down():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))
    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(invested=True, average_price=50.0, quantity=5),
        now=now,
        enforce_market_hours=False,
    )
    assert signal.action == "HOLD"
    assert "kein Nachkauf im Verlust" in signal.headline


def test_buy_signal_requires_short_term_volume_confirmation():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    frames = _frames(now)
    frames["1m"]["volume"] = 0.0
    frames["5m"]["volume"] = 0.0
    analyses, enriched, _ = analyze_timeframes(frames)
    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        enforce_market_hours=False,
    )
    assert signal.action == "WAIT"
    assert any("Volumen zu schwach" in reason for reason in signal.reasons)


def test_bearish_one_and_five_minute_confirmation_creates_sell_signal():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, errors = analyze_timeframes(_frames(now, bearish=True))
    assert errors == {}
    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(invested=True, average_price=21.0, quantity=5),
        now=now,
        enforce_market_hours=False,
    )
    assert signal.action == "SELL"
    assert analyses["1m"].score < 38
    assert analyses["5m"].score < 42


def test_stale_free_data_never_releases_short_term_trade():
    frame_time = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(frame_time))
    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=frame_time + timedelta(minutes=20),
        enforce_market_hours=False,
    )
    assert signal.action == "NO_SIGNAL"
    assert "verzögert" in signal.headline


def test_resampling_uses_complete_source_groups_only():
    index = pd.date_range("2026-08-12 08:05", periods=8, freq="5min", tz="UTC")
    values = np.arange(8, dtype=float) + 10
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values + 0.5,
            "volume": np.full(8, 100.0),
        },
        index=index,
    )
    result = resample_ohlcv(
        frame,
        "15min",
        minimum_source_rows=1,
        drop_future_label=True,
    )
    assert len(result) == 2
    assert list(result["volume"]) == [300.0, 300.0]


def test_loader_uses_fresher_german_venue_without_mixing_symbols():
    now = pd.Timestamp("2026-08-12 10:00", tz="UTC")

    class VenueProvider:
        name = "Testquelle"
        is_demo = False

        def __init__(self) -> None:
            self.requests: list[MarketDataRequest] = []

        def history(self, request: MarketDataRequest) -> pd.DataFrame:
            self.requests.append(request)
            rows = 300
            interval = {"1m": "1min", "5m": "5min", "1h": "1h", "1d": "1D"}[request.interval]
            stale = timedelta(minutes=30) if request.symbol == "RQ0.F" else timedelta(minutes=2)
            index = pd.date_range(end=now - stale, periods=rows, freq=interval).as_unit("ns")
            values = np.linspace(10, 12, rows)
            return pd.DataFrame(
                {
                    "open": values,
                    "high": values + 0.1,
                    "low": values - 0.1,
                    "close": values + 0.02,
                    "volume": np.full(rows, 1000.0),
                },
                index=index,
            )

    provider = VenueProvider()
    bundle = load_dwave_timeframes(provider)

    assert bundle.symbol == "RQ0.SG"
    assert bundle.venue == "Stuttgart"
    assert {request.symbol for request in provider.requests if request.interval != "1m"} == {"RQ0.SG"}
    assert {"1m", "5m", "15m", "1h", "1d", "1wk", "1mo"} <= set(bundle.frames)
