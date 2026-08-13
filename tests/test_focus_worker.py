from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.focus.analysis import IntradaySignal
from src.focus.paper import PAPER_PORTFOLIO_NAME
from src.focus.quote import LiveQuote
from src.focus.worker import FocusPaperWorker, session_is_active


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
        target=19.0,
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


def test_worker_executes_paper_order_and_persists_heartbeat(store, monkeypatch):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    monkeypatch.setattr("src.focus.worker.build_market_signal", lambda *_args, **_kwargs: _buy_signal())
    worker = FocusPaperWorker(store, provider=FakeStock3Provider(now), clock=lambda: now)

    cycle = worker.run_once()

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
