from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.focus.analysis import IntradaySignal
from src.focus.paper import PAPER_PORTFOLIO_NAME, run_paper_account
from src.focus.quote import LiveQuote


def _quote(bid: float, ask: float, timestamp: datetime) -> LiveQuote:
    return LiveQuote(
        provider="stock3 öffentlicher L&S-Kurs",
        venue="Lang & Schwarz",
        isin="US26740W1099",
        bid=bid,
        ask=ask,
        bid_size=None,
        ask_size=None,
        last=bid,
        high=ask,
        low=bid,
        change_percent=1.0,
        volume=None,
        fetched_at=timestamp,
        refresh_seconds=10,
        quoted_at=timestamp,
    )


def _signal(action: str, price: float) -> IntradaySignal:
    return IntradaySignal(
        action=action,
        headline=action,
        score=72.0 if action == "BUY" else 30.0,
        strength="stark",
        color="#22c55e" if action == "BUY" else "#ef4444",
        current_price=price,
        entry_low=price - 0.02 if action == "BUY" else None,
        entry_high=price + 0.02 if action == "BUY" else None,
        stop_loss=price - 0.25 if action == "BUY" else None,
        target=price + 1.2 if action == "BUY" else None,
        holding_period="5–30 Minuten",
        reasons=(),
        warning="",
        data_age_minutes=0.0,
        market_open=True,
    )


def test_focus_paper_account_starts_with_2000_and_books_real_spread_and_fee(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    buy_quote = _quote(18.0, 18.1, now)

    bought = run_paper_account(store, buy_quote, _signal("BUY", buy_quote.bid), signal_at=now)

    assert bought.initial_capital == 2_000.0
    assert bought.state == "INVESTIERT"
    assert 1_000.0 <= bought.cash < 2_000.0
    assert bought.quantity > 0
    assert bought.average_price == pytest.approx(18.1 + buy_quote.midpoint * 0.0005)
    assert bought.total_fees == 1.0
    assert bought.total_spread_cost > 0
    assert bought.total_slippage_cost > 0
    assert bought.result_eur < -1.0
    portfolio = next(item for item in store.list_portfolios() if item.name == PAPER_PORTFOLIO_NAME)
    assert len(store.list_orders(portfolio.id)) == 1

    duplicate = run_paper_account(store, buy_quote, _signal("BUY", buy_quote.bid), signal_at=now)
    assert duplicate.quantity == bought.quantity
    assert len(store.list_orders(portfolio.id)) == 1

    sell_quote = _quote(18.4, 18.5, now + timedelta(minutes=5))
    sold = run_paper_account(
        store,
        sell_quote,
        _signal("SELL", sell_quote.bid),
        signal_at=now + timedelta(minutes=5),
    )
    assert sold.state == "CASH"
    assert sold.quantity == 0
    assert sold.total_fees == 2.0
    assert sold.total_transaction_costs > sold.total_fees
    assert sold.completed_trades == 1
    assert len(store.list_orders(portfolio.id)) == 2


def test_focus_paper_account_rejects_target_that_does_not_cover_roundtrip_costs(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    quote = _quote(18.0, 18.05, now)
    weak_target = replace(_signal("BUY", quote.bid), target=18.08)

    account = run_paper_account(store, quote, weak_target, signal_at=now)

    assert account.state == "WARTET · KOSTEN"
    assert account.cash == 2_000.0
    assert account.total_transaction_costs == 0


def test_focus_paper_account_requires_entry_confirmation(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    quote = _quote(18.0, 18.05, now)

    account = run_paper_account(
        store,
        quote,
        _signal("BUY", quote.bid),
        signal_at=now,
        entry_confirmed=False,
    )

    assert account.state == "WARTET · BESTÄTIGUNG"
    assert account.quantity == 0


def test_focus_paper_account_pauses_after_an_exit(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    quote = _quote(18.0, 18.05, now)
    run_paper_account(store, quote, _signal("BUY", quote.bid), signal_at=now)
    exit_quote = _quote(19.3, 19.35, now + timedelta(minutes=6))
    sold = run_paper_account(
        store,
        exit_quote,
        _signal("SELL", exit_quote.bid),
        signal_at=now + timedelta(minutes=6),
    )
    assert sold.state == "CASH"

    reentry = run_paper_account(
        store,
        exit_quote,
        _signal("BUY", exit_quote.bid),
        signal_at=now + timedelta(minutes=10),
    )
    assert reentry.state == "WARTET · 15 MIN PAUSE"
    assert reentry.quantity == 0


def test_focus_paper_account_stops_after_four_daily_roundtrips(store):
    now = datetime(2026, 8, 13, 7, 30, tzinfo=UTC)
    for index in range(4):
        entry_at = now + timedelta(minutes=index * 25)
        price = 18.0 + index * 1.5
        quote = _quote(price, price + 0.05, entry_at)
        bought = run_paper_account(store, quote, _signal("BUY", quote.bid), signal_at=entry_at)
        assert bought.state == "INVESTIERT"
        exit_at = entry_at + timedelta(minutes=6)
        exit_quote = _quote(price + 1.3, price + 1.35, exit_at)
        sold = run_paper_account(
            store,
            exit_quote,
            _signal("SELL", exit_quote.bid),
            signal_at=exit_at,
        )
        assert sold.state == "CASH"

    fifth_at = now + timedelta(minutes=100)
    fifth_quote = _quote(24.0, 24.05, fifth_at)
    blocked = run_paper_account(
        store,
        fifth_quote,
        _signal("BUY", fifth_quote.bid),
        signal_at=fifth_at,
    )

    assert blocked.state == "WARTET · TAGESLIMIT"
    assert blocked.completed_trades == 4


def test_focus_paper_account_waits_when_spread_is_too_wide(store):
    now = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
    quote = _quote(18.0, 18.2, now)

    account = run_paper_account(store, quote, _signal("BUY", quote.bid), signal_at=now)

    assert account.state == "WARTET · SPREAD"
    assert account.cash == 2_000.0
    assert account.quantity == 0
    assert account.total_transaction_costs == 0


def test_focus_paper_account_never_executes_stale_market_signal(store):
    now = datetime(2026, 8, 13, 21, 30, tzinfo=UTC)
    quote = _quote(18.0, 18.05, now)
    stale = replace(_signal("BUY", quote.bid), data_age_minutes=10.0)

    account = run_paper_account(store, quote, stale, signal_at=now)

    assert account.cash == 2_000.0
    assert account.quantity == 0
    portfolio = next(item for item in store.list_portfolios() if item.name == PAPER_PORTFOLIO_NAME)
    assert store.list_orders(portfolio.id) == []
