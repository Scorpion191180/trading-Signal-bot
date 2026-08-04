from __future__ import annotations

from src.config import STRATEGIES
from src.portfolio.backtest import run_backtest


def test_backtest_uses_next_candle_and_returns_metrics(market_frame):
    result = run_backtest(market_frame, STRATEGIES["Normal"])
    assert result.initial_capital == 10_000
    assert result.final_capital > 0
    assert not result.equity_curve.empty
    assert result.max_drawdown_pct >= 0
    assert result.trades
    assert all(trade.entry_signal_time < trade.entry_time <= trade.exit_time for trade in result.trades)


def test_future_change_does_not_change_first_entry(market_frame):
    baseline = run_backtest(market_frame, STRATEGIES["Normal"])
    changed = market_frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 5
    modified = run_backtest(changed, STRATEGIES["Normal"])
    assert baseline.trades[0].entry_time == modified.trades[0].entry_time
    assert baseline.trades[0].entry_price == modified.trades[0].entry_price
