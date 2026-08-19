from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.focus.patterns import candlestick_pattern_score, scan_candlestick_patterns


def _downtrend_with_bullish_engulfing() -> pd.DataFrame:
    index = pd.date_range("2026-08-19 08:00:00Z", periods=24, freq="5min")
    close = np.linspace(10.60, 10.02, len(index))
    open_ = close + 0.025
    high = np.maximum(open_, close) + 0.035
    low = np.minimum(open_, close) - 0.035
    open_[-2], close[-2], high[-2], low[-2] = 10.08, 9.92, 10.10, 9.89
    open_[-1], close[-1], high[-1], low[-1] = 9.90, 10.11, 10.14, 9.86
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(index), 1_000.0),
        },
        index=index,
    )


def test_bullish_engulfing_is_detected_only_after_confirmation_close():
    frame = _downtrend_with_bullish_engulfing()
    before_confirmation = scan_candlestick_patterns(frame.iloc[:-1], minimum_confidence=60)
    confirmed = scan_candlestick_patterns(frame, minimum_confidence=60)

    assert not any(item.name == "Bullish Engulfing" for item in before_confirmation)
    pattern = next(item for item in confirmed if item.name == "Bullish Engulfing")
    assert pattern.direction == "BULLISH"
    assert pattern.timestamp == frame.index[-1].to_pydatetime()
    assert pattern.stop_loss < pattern.price < pattern.target
    assert pattern.confidence >= 75


def test_pattern_result_does_not_change_when_future_candles_are_appended():
    frame = _downtrend_with_bullish_engulfing()
    original = next(
        item
        for item in scan_candlestick_patterns(frame, minimum_confidence=60)
        if item.name == "Bullish Engulfing"
    )
    future_index = pd.date_range(
        frame.index[-1].to_pydatetime() + timedelta(minutes=5),
        periods=8,
        freq="5min",
    )
    future = pd.DataFrame(
        {
            "open": np.linspace(10.11, 10.28, len(future_index)),
            "high": np.linspace(10.16, 10.33, len(future_index)),
            "low": np.linspace(10.08, 10.25, len(future_index)),
            "close": np.linspace(10.14, 10.31, len(future_index)),
            "volume": np.full(len(future_index), 1_100.0),
        },
        index=future_index,
    )
    extended = next(
        item
        for item in scan_candlestick_patterns(pd.concat((frame, future)), minimum_confidence=60)
        if item.name == "Bullish Engulfing" and item.timestamp == original.timestamp
    )

    assert extended == original


def test_bullish_and_bearish_patterns_move_score_symmetrically():
    bullish = scan_candlestick_patterns(_downtrend_with_bullish_engulfing())
    mirrored = _downtrend_with_bullish_engulfing().copy()
    center = 10.0
    for column in ("open", "high", "low", "close"):
        mirrored[column] = center * 2 - mirrored[column]
    mirrored[["high", "low"]] = mirrored[["low", "high"]].to_numpy()
    bearish = scan_candlestick_patterns(mirrored)

    assert candlestick_pattern_score(bullish) > 50
    assert candlestick_pattern_score(bearish) < 50
