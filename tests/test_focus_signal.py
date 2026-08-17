from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import numpy as np
import pandas as pd

from src.data import MarketDataRequest
from src.focus.analysis import (
    MICROTREND_CONTINUATION_EVENT,
    SPEC_BY_KEY,
    US_OPENING_REVERSAL_EVENT,
    ExternalMarketContext,
    FocusPosition,
    _microtrend_continuation,
    _profit_exhaustion,
    _rolling_linear_regression,
    _smart_money_context,
    _us_opening_reversal,
    add_focus_indicators,
    analyze_timeframes,
    build_intraday_signal,
    build_market_signal,
    build_strategy_ensemble,
)
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


def test_vectorized_linear_regression_matches_direct_window_calculation():
    series = pd.Series(np.linspace(10, 12, 40) + np.sin(np.arange(40) / 3))
    actual = _rolling_linear_regression(series, 11)
    expected = series.rolling(11).apply(
        lambda values: np.polyfit(np.arange(11), values, 1)[0] * 10
        + np.polyfit(np.arange(11), values, 1)[1],
        raw=True,
    )
    assert np.allclose(actual.dropna(), expected.dropna())


def test_liquidity_sweep_then_displacement_confirms_bullish_structure_change():
    index = pd.date_range("2026-08-14 08:00:00Z", periods=36, freq="5min")
    close = np.full(36, 10.0)
    open_ = np.full(36, 10.0)
    high = np.full(36, 10.05)
    low = np.full(36, 9.95)
    open_[34], close[34], high[34], low[34] = 10.02, 10.0, 10.03, 9.78
    open_[35], close[35], high[35], low[35] = 10.0, 10.32, 10.34, 9.99
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000.0},
        index=index,
    )

    context = _smart_money_context(add_focus_indicators(frame, SPEC_BY_KEY["5m"]))

    assert context.bullish_reversal is True
    assert context.bearish_reversal is False
    assert context.demand_low is not None
    assert context.demand_high is not None
    assert "bullischer Strukturwechsel" in context.event


def test_us_open_reversal_detects_selloff_sweep_and_reclaim():
    index = pd.date_range("2026-08-14 12:50:00Z", periods=41, freq="1min")
    close = np.linspace(18.08, 17.82, len(index))
    open_ = np.concatenate(([close[0] + 0.01], close[:-1]))
    high = np.maximum(open_, close) + 0.025
    low = np.minimum(open_, close) - 0.025
    open_[-1], high[-1], low[-1], close[-1] = 17.805, 17.900, 17.675, 17.900
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 0.0},
        index=index,
    )
    enriched = add_focus_indicators(frame, SPEC_BY_KEY["1m"])

    reversal = _us_opening_reversal(
        enriched,
        datetime(2026, 8, 14, 13, 31, tzinfo=UTC),
        spread_percent=0.20,
    )

    assert reversal.active is True
    assert reversal.event == US_OPENING_REVERSAL_EVENT
    assert reversal.event_low == 17.675
    assert reversal.stop_loss < reversal.reclaimed_level < 17.900
    assert reversal.target > 18.20


def test_us_open_reversal_is_not_a_blind_timed_entry():
    index = pd.date_range("2026-08-14 12:50:00Z", periods=41, freq="1min")
    close = np.linspace(18.00, 18.10, len(index))
    frame = pd.DataFrame(
        {
            "open": close - 0.005,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": 0.0,
        },
        index=index,
    )

    reversal = _us_opening_reversal(
        add_focus_indicators(frame, SPEC_BY_KEY["1m"]),
        datetime(2026, 8, 14, 13, 31, tzinfo=UTC),
        spread_percent=0.20,
    )

    assert reversal.active is False


def test_microtrend_continuation_detects_four_candle_staircase_after_pullback():
    index = pd.date_range("2026-08-14 15:32:00Z", periods=24, freq="1min")
    close = np.full(24, 18.12)
    open_ = np.full(24, 18.11)
    high = np.full(24, 18.14)
    low = np.full(24, 18.09)
    actual = (
        (18.15, 18.16, 18.095, 18.105),
        (18.10, 18.135, 18.095, 18.125),
        (18.125, 18.150, 18.095, 18.105),
        (18.110, 18.125, 18.100, 18.100),
        (18.095, 18.115, 18.095, 18.115),
        (18.110, 18.160, 18.105, 18.155),
        (18.150, 18.180, 18.145, 18.170),
        (18.160, 18.170, 18.135, 18.145),
        (18.135, 18.155, 18.095, 18.100),
        (18.110, 18.115, 18.090, 18.115),
        (18.125, 18.145, 18.115, 18.135),
        (18.145, 18.145, 18.110, 18.135),
        (18.125, 18.160, 18.125, 18.160),
        (18.155, 18.175, 18.155, 18.175),
        (18.165, 18.185, 18.165, 18.175),
        (18.175, 18.200, 18.170, 18.190),
    )
    for offset, values in enumerate(actual, start=8):
        open_[offset], high[offset], low[offset], close[offset] = values
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "atr_14": np.full(24, 0.0332),
            "ema_fast": np.full(24, 18.160),
            "ema_slow": np.full(24, 18.145),
            "rsi_14": np.full(24, 58.7),
        },
        index=index,
    )

    continuation = _microtrend_continuation(frame, spread_percent=0.22)

    assert continuation.active is True
    assert continuation.event == MICROTREND_CONTINUATION_EVENT
    assert continuation.breakout_level == 18.185
    assert continuation.stop_loss < 18.170
    assert continuation.target > 18.19
    assert (continuation.target - 18.19) / (18.19 - continuation.stop_loss) >= 2.1


def test_profit_exhaustion_requires_red_reversal_after_extreme_rsi():
    frame = pd.DataFrame(
        {
            "open": [18.42, 18.45, 18.47, 18.49, 18.505],
            "high": [18.46, 18.48, 18.50, 18.52, 18.505],
            "low": [18.41, 18.44, 18.46, 18.48, 18.45],
            "close": [18.45, 18.47, 18.49, 18.515, 18.49],
            "atr_14": [0.04] * 5,
            "rsi_14": [74.0, 78.0, 80.4, 82.3, 74.6],
        },
        index=pd.date_range("2026-08-14 16:16:00Z", periods=5, freq="1min"),
    )

    assert _profit_exhaustion(frame) is True


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
    assert buy.holding_period == "adaptiv · meist 5–30 Minuten, maximal 120 Minuten"
    assert buy.entry_low < buy.current_price < buy.entry_high
    assert buy.stop_loss < buy.current_price < buy.target
    assert buy.forecast_direction == "EHER STEIGEND"
    assert buy.forecast_low < buy.current_price < buy.forecast_high
    assert len(buy.strategy_votes) == 7
    assert [item.minutes for item in buy.trend_forecasts] == [5, 15, 30, 60, 120]
    assert all(item.expected_low < item.expected_price < item.expected_high for item in buy.trend_forecasts)
    assert any("OTT/UT" in vote for vote in buy.strategy_votes)


def test_five_minute_forecast_reacts_to_fast_bearish_price_reversal():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    baseline_frames = _frames(now)
    baseline_analyses, baseline_enriched, _ = analyze_timeframes(baseline_frames)
    baseline = build_strategy_ensemble(
        baseline_analyses,
        baseline_enriched,
        float(baseline_frames["1m"]["close"].iloc[-1]),
    )

    reversal_frames = {key: frame.copy() for key, frame in baseline_frames.items()}
    minute = reversal_frames["1m"]
    close_column = minute.columns.get_loc("close")
    open_column = minute.columns.get_loc("open")
    high_column = minute.columns.get_loc("high")
    low_column = minute.columns.get_loc("low")
    reversal_closes = float(minute["close"].iloc[-9]) - np.linspace(0.01, 0.32, 8)
    for offset, close in enumerate(reversal_closes, start=len(minute) - 8):
        previous_close = float(minute["close"].iloc[offset - 1])
        minute.iloc[offset, close_column] = close
        minute.iloc[offset, open_column] = previous_close
        minute.iloc[offset, high_column] = max(previous_close, close) + 0.02
        minute.iloc[offset, low_column] = min(previous_close, close) - 0.02

    reversal_analyses, reversal_enriched, errors = analyze_timeframes(reversal_frames)
    assert errors == {}
    reversal = build_strategy_ensemble(
        reversal_analyses,
        reversal_enriched,
        float(minute["close"].iloc[-1]),
    )

    assert baseline.horizons[0].direction == "STEIGEND"
    assert reversal.horizons[0].direction != "STEIGEND"
    assert reversal.horizons[0].expected_price < baseline.horizons[0].expected_price


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


def test_wide_spread_blocks_a_short_term_entry():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))

    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        enforce_market_hours=False,
        spread_percent=1.2,
    )

    assert signal.action == "WAIT"
    assert "Spread" in signal.warning
    assert signal.spread_percent == 1.2


def test_external_market_and_news_context_changes_score_but_stays_bounded():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))
    positive = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        enforce_market_hours=False,
        external_context=ExternalMarketContext(
            score=85,
            reasons=("D-Wave USA und Nasdaq positiv",),
            headlines=("Bestätigte Unternehmensmeldung",),
            available=True,
        ),
    )
    negative = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        enforce_market_hours=False,
        external_context=ExternalMarketContext(
            score=15,
            reasons=("D-Wave USA und Nasdaq negativ",),
            available=True,
        ),
    )

    assert positive.score > negative.score
    assert positive.score - negative.score <= 14
    assert positive.external_context_score == 85
    assert positive.latest_news == ("Bestätigte Unternehmensmeldung",)


def test_live_tradegate_price_is_used_for_position_and_display():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))
    signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(invested=True, average_price=12.0, quantity=5),
        now=now,
        enforce_market_hours=False,
        live_price=12.5,
    )
    assert signal.current_price == 12.5


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

    quote_only_signal = build_market_signal(
        analyses,
        enriched,
        now=now,
        enforce_market_hours=False,
        require_volume_confirmation=False,
    )
    assert quote_only_signal.action == "BUY"
    assert any("L&S-Bid-Quelle ohne Volumen" in reason for reason in quote_only_signal.reasons)


def test_market_signal_is_independent_of_private_position_and_can_sell():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    bullish_analyses, bullish_enriched, _ = analyze_timeframes(_frames(now))
    bearish_analyses, bearish_enriched, _ = analyze_timeframes(_frames(now, bearish=True))

    assert (
        build_market_signal(
            bullish_analyses,
            bullish_enriched,
            now=now,
            enforce_market_hours=False,
        ).action
        == "BUY"
    )
    assert (
        build_market_signal(
            bearish_analyses,
            bearish_enriched,
            now=now,
            enforce_market_hours=False,
        ).action
        == "SELL"
    )


def test_technical_buy_remains_visible_while_wide_spread_blocks_execution_layer():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))

    signal = build_market_signal(
        analyses,
        enriched,
        now=now,
        enforce_market_hours=False,
        spread_percent=1.2,
        enforce_liquidity_filter=False,
    )

    assert signal.action == "BUY"
    assert "Spread" in signal.warning


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


def test_lang_schwarz_session_remains_open_until_23_but_tradegate_does_not():
    now = datetime(2026, 8, 12, 20, 30, tzinfo=UTC)
    analyses, enriched, _ = analyze_timeframes(_frames(now))

    lang_schwarz = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        session_close=time(23, 0),
    )
    tradegate = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        now=now,
        session_close=time(22, 0),
    )

    assert lang_schwarz.market_open is True
    assert tradegate.market_open is False
    assert "geschlossen" in tradegate.headline


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
