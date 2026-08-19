from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.focus.analysis import IntradaySignal
from src.focus.paper import PAPER_PORTFOLIO_NAME, current_paper_account
from src.focus.quote import LiveQuote
from src.focus.stock3 import Stock3Instrument
from src.focus.worker import FocusPaperWorker, _latest_trading_day, session_is_active


class FakeStock3Provider:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def quote(self) -> LiveQuote:
        return LiveQuote(
            provider="stock3 Test",
            venue="Lang & Schwarz",
            isin="US26740W1099",
            bid=18.0,
            ask=18.05,
            bid_size=None,
            ask_size=None,
            last=18.0,
            high=18.2,
            low=17.8,
            change_percent=1.0,
            volume=None,
            fetched_at=self.now,
            refresh_seconds=10,
            quoted_at=self.now,
        )

    def history(self, resolution_seconds: int) -> pd.DataFrame:
        rows = 1_200 if resolution_seconds == 86400 else 360
        frequency = {
            60: "1min",
            300: "5min",
            3600: "1h",
            86400: "1D",
        }[resolution_seconds]
        index = pd.date_range(end=pd.Timestamp(self.now), periods=rows, freq=frequency)
        prices = np.linspace(14.0, 18.0, rows) + np.sin(np.arange(rows) / 9) * 0.03
        frame = pd.DataFrame(
            {
                "open": prices - 0.01,
                "high": prices + 0.04,
                "low": prices - 0.04,
                "close": prices,
                "volume": np.zeros(rows),
            },
            index=index,
        )
        frame.attrs["provider"] = "stock3 · L&S Bid"
        frame.attrs["quote_type"] = "bid"
        return frame


def _buy_signal() -> IntradaySignal:
    return IntradaySignal(
        action="BUY",
        headline="KAUFEN",
        score=72.0,
        strength="stark",
        color="#22c55e",
        current_price=18.0,
        entry_low=17.98,
        entry_high=18.02,
        stop_loss=17.5,
        target=19.2,
        holding_period="5–30 Minuten",
        reasons=(),
        warning="",
        data_age_minutes=0.0,
        market_open=True,
        forecast_direction="EHER STEIGEND",
        forecast_low=17.9,
        forecast_high=18.3,
        market_regime="Trend",
        strategy_votes=("Trend 72 ↑",),
        spread_percent=0.28,
    )


def test_session_window_uses_berlin_time():
    assert session_is_active(datetime(2026, 8, 13, 5, 30, tzinfo=UTC))
    assert session_is_active(datetime(2026, 8, 13, 21, 0, tzinfo=UTC))
    assert not session_is_active(datetime(2026, 8, 13, 21, 1, tzinfo=UTC))
    assert not session_is_active(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))


def test_sparse_bid_changes_become_continuous_minute_candles():
    now = datetime(2026, 8, 14, 6, 7, tzinfo=UTC)
    quote = FakeStock3Provider(now).quote()
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-08-14 05:30:00Z"),
            pd.Timestamp("2026-08-14 05:33:00Z"),
            pd.Timestamp("2026-08-14 06:07:00Z"),
        ],
        name="timestamp",
    )
    sparse = pd.DataFrame(
        {
            "open": [17.9, 17.95, 18.0],
            "high": [17.95, 18.0, 18.05],
            "low": [17.88, 17.94, 17.98],
            "close": [17.94, 17.99, 18.0],
            "volume": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    sparse.attrs["quote_type"] = "bid"

    completed = _latest_trading_day(sparse, quote)

    assert len(completed) == 38
    assert completed.index[0] == index[0]
    assert completed.index[-1] == index[-1]
    assert completed.attrs["filled_unchanged_minutes"] == 35
    assert completed.loc[pd.Timestamp("2026-08-14 05:31:00Z"), "close"] == 17.94
    assert completed.iloc[-1]["close"] == quote.bid


def test_worker_executes_paper_order_and_persists_heartbeat(store, monkeypatch):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    monkeypatch.setattr("src.focus.worker.build_market_signal", lambda *_args, **_kwargs: _buy_signal())
    worker = FocusPaperWorker(store, provider=FakeStock3Provider(now), clock=lambda: now)

    first = worker.run_once()
    cycle = worker.run_once()

    assert first is not None and first.account.state == "INVESTIERT"
    assert cycle is not None
    assert cycle.account.state == "INVESTIERT"
    portfolio = next(item for item in store.list_portfolios() if item.name == PAPER_PORTFOLIO_NAME)
    assert len(store.list_orders(portfolio.id)) == 1
    status = store.get_focus_bot_status()
    assert status is not None
    assert status.run_state == "ACTIVE"
    assert status.signal_action == "BUY"
    assert status.account_state == "INVESTIERT"


def test_worker_pauses_without_loading_market_data_outside_session(store):
    saturday = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    worker = FocusPaperWorker(store, provider=FakeStock3Provider(saturday), clock=lambda: saturday)

    assert worker.run_once() is None
    status = store.get_focus_bot_status()
    assert status is not None
    assert status.run_state == "PAUSED"
    assert "07:30" in status.message


def test_worker_does_not_load_market_data_or_trade_when_bot_is_disabled(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    account = current_paper_account(store)
    store.set_portfolio_active(account.portfolio_id, False)
    worker = FocusPaperWorker(store, provider=FakeStock3Provider(now), clock=lambda: now)

    assert worker.run_once() is None
    assert store.list_orders(account.portfolio_id) == []
    status = store.get_focus_bot_status()
    assert status is not None
    assert status.run_state == "DISABLED"
    assert "ausgeschaltet" in status.message


def test_worker_can_paper_trade_dwave_and_a_comparison_asset(store, monkeypatch):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    spacex = Stock3Instrument("SpaceX", 96904496, "US84615Q1031", "spacex")
    monkeypatch.setattr("src.focus.worker.COMPARISON_INSTRUMENTS", (spacex,))
    monkeypatch.setattr("src.focus.worker.COMPARISON_POLL_SECONDS", 60)
    monkeypatch.setattr("src.focus.worker.monotonic", lambda: 1_000.0)
    monkeypatch.setattr("src.focus.worker.build_market_signal", lambda *_args, **_kwargs: _buy_signal())
    worker = FocusPaperWorker(
        store,
        provider=FakeStock3Provider(now),
        comparison_provider_factory=lambda _instrument: FakeStock3Provider(now),
        clock=lambda: now,
    )

    worker.run_once()
    cycle = worker.run_once()

    assert cycle is not None
    positions = store.list_positions(cycle.account.portfolio_id)
    assert {position.symbol for position in positions} == {"RQ0", spacex.isin}
    assert cycle.account.open_positions == 2
    assert {order.symbol for order in store.list_orders(cycle.account.portfolio_id)} == {
        "RQ0",
        spacex.isin,
    }
    status = store.get_focus_bot_status()
    assert status is not None
    assert "1/1 weitere Aktien zuletzt geprüft" in status.message
