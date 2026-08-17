from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.focus.analysis import FocusPosition
from src.focus.page import UI_REFRESH_SECONDS, _apply_live_quote, _local_trade_time, _signal_mode_text
from src.focus.quote import LiveQuote


def _quote(price: float = 18.3) -> LiveQuote:
    return LiveQuote(
        provider="Lang & Schwarz",
        venue="Lang & Schwarz",
        isin="US26740W1099",
        bid=price,
        ask=price,
        bid_size=None,
        ask_size=None,
        last=price,
        high=price,
        low=price,
        change_percent=0.0,
        volume=1000,
        fetched_at=datetime(2026, 8, 13, 18, 0, tzinfo=UTC),
        refresh_seconds=10,
    )


def test_signal_mode_is_independent_of_private_position():
    assert "KAUFEN" in _signal_mode_text(FocusPosition(), _quote())

    losing_position = FocusPosition(invested=True, average_price=21.96, quantity=67.5)
    explanation = _signal_mode_text(losing_position, _quote())

    assert "KAUFEN/VERKAUFEN" in explanation
    assert "unabhängig" in explanation
    assert "-16.7 %" in explanation


def test_trade_times_are_shown_in_berlin_time():
    local = _local_trade_time(datetime(2026, 8, 13, 13, 30, tzinfo=UTC))

    assert local.strftime("%H:%M") == "15:30"


def test_live_quote_updates_current_candle_each_second():
    quote = _quote(18.4)
    quote_time = pd.Timestamp(quote.fetched_at).floor("min")
    candles = pd.DataFrame(
        {"open": [18.3], "high": [18.35], "low": [18.25], "close": [18.3], "volume": [0.0]},
        index=pd.DatetimeIndex([quote_time]),
    )

    updated = _apply_live_quote(candles, quote)

    assert UI_REFRESH_SECONDS == 1
    assert updated.loc[quote_time, "close"] == 18.4
    assert updated.loc[quote_time, "high"] == 18.4
