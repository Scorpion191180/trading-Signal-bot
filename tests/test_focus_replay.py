from __future__ import annotations

from datetime import UTC

import pandas as pd
import pytest

from src.focus.analysis import US_OPENING_REVERSAL_EVENT, IntradaySignal
from src.focus.replay import replay_focus_day


def _candles() -> pd.DataFrame:
    index = pd.date_range("2026-08-14 10:00", periods=4, freq="1min", tz=UTC)
    return pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.5, 10.5],
            "high": [10.05, 10.6, 10.55, 10.55],
            "low": [9.98, 9.99, 10.45, 10.45],
            "close": [10.0, 10.5, 10.5, 10.5],
            "volume": [0.0, 0.0, 0.0, 0.0],
        },
        index=index,
    )


def _buy_signal(*, opening_reversal: bool = False) -> IntradaySignal:
    return IntradaySignal(
        action="BUY",
        headline="Testkauf",
        score=80.0,
        strength="stark",
        color="#22c55e",
        current_price=10.0,
        entry_low=9.99,
        entry_high=10.02,
        stop_loss=9.90,
        target=10.50,
        holding_period="5–30 Minuten",
        reasons=(),
        warning="",
        data_age_minutes=0.0,
        market_open=True,
        structure_event=US_OPENING_REVERSAL_EVENT if opening_reversal else "",
    )


def test_replay_uses_historical_spread_and_intraminute_target(monkeypatch):
    bid = _candles()
    ask = bid.copy()
    for column in ("open", "high", "low", "close"):
        ask[column] += 0.02
    monkeypatch.setattr("src.focus.replay.analyze_timeframes", lambda _frames: ({}, {}, {}))
    monkeypatch.setattr(
        "src.focus.replay.build_market_signal",
        lambda *_args, **_kwargs: _buy_signal(),
    )

    result = replay_focus_day(
        bid_minutes=bid,
        ask_minutes=ask,
        five_minutes=bid,
        hourly=bid,
        daily=bid,
        confirmation_observations=1,
    )

    assert result.completed_trades == 1
    assert [order.side for order in result.orders] == ["BUY", "SELL"]
    assert result.orders[1].market_price == pytest.approx(10.51)
    assert result.transaction_costs > 2.0
    assert result.pnl_eur > 0
    assert result.open_position is False


def test_replay_requires_positive_confirmation_count():
    candles = _candles()

    with pytest.raises(ValueError, match="Bestätigungsbeobachtungen"):
        replay_focus_day(
            bid_minutes=candles,
            ask_minutes=candles,
            five_minutes=candles,
            hourly=candles,
            daily=candles,
            confirmation_observations=0,
        )


def test_replay_uses_closed_minute_as_proxy_for_live_opening_confirmation(monkeypatch):
    bid = _candles()
    ask = bid.copy()
    for column in ("open", "high", "low", "close"):
        ask[column] += 0.02
    monkeypatch.setattr("src.focus.replay.analyze_timeframes", lambda _frames: ({}, {}, {}))
    monkeypatch.setattr(
        "src.focus.replay.build_market_signal",
        lambda *_args, **_kwargs: _buy_signal(opening_reversal=True),
    )

    result = replay_focus_day(
        bid_minutes=bid,
        ask_minutes=ask,
        five_minutes=bid,
        hourly=bid,
        daily=bid,
        confirmation_observations=2,
    )

    assert result.completed_trades == 1
    assert result.orders[0].side == "BUY"
    assert "US-Eröffnungs-Reversal" in result.orders[0].reason
