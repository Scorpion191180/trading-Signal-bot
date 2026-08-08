from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.database.models import StrategyVersion, WeightVersion
from src.database.repositories import DuplicateOrderError, PortfolioError


def test_defaults_and_watchlist_crud(store):
    assert len(store.list_watchlist()) == 9
    item = store.add_watchlist_item("test", company="Test AG", trading_allowed=True)
    assert item.symbol == "TEST"
    assert item.trading_allowed is True
    store.update_watchlist_settings(
        item.id,
        priority=True,
        trading_allowed=False,
        interval="15m",
        extended_hours=True,
    )
    updated = next(value for value in store.list_watchlist() if value.symbol == "TEST")
    assert updated.priority is True
    assert updated.trading_allowed is False
    assert updated.analysis_only is True
    assert updated.interval == "15m"
    assert updated.extended_hours is True
    store.delete_watchlist_item(item.id)
    assert all(value.symbol != "TEST" for value in store.list_watchlist())
    assert {value.name for value in store.list_portfolios()} == {"Defensiv", "Normal", "Aggressiv"}
    with store.sessions() as session:
        assert session.scalar(select(func.count()).select_from(StrategyVersion)) == 3
        assert session.scalar(select(WeightVersion.version)) == "v1"


def test_real_position_crud(store):
    position = store.add_real_position(company="Beispiel", symbol="BSP", quantity=2, average_price=25)
    assert store.list_real_positions()[0].symbol == "BSP"
    store.delete_real_position(position.id)
    assert store.list_real_positions() == []


def test_virtual_buy_sell_and_journal(store):
    portfolio = next(value for value in store.list_portfolios() if value.name == "Normal")
    order = store.open_position(
        portfolio_id=portfolio.id,
        symbol="TEST",
        quantity=10,
        market_price=100,
        stop_loss=95,
        take_profit=110,
        reason="Testsignal",
        signal_score=70,
        weight_version="v1",
        provider="Test-Realdaten",
        is_demo=False,
        idempotency_key="buy-1",
        news_factor=0.7,
        news_ids=("entry-news-1", "entry-news-2"),
    )
    assert order.side == "BUY"
    assert len(store.list_positions(portfolio.id)) == 1
    with pytest.raises(DuplicateOrderError):
        store.open_position(
            portfolio_id=portfolio.id,
            symbol="OTHER",
            quantity=1,
            market_price=100,
            stop_loss=95,
            take_profit=110,
            reason="Doppelt",
            signal_score=70,
            weight_version="v1",
            provider="Test-Realdaten",
            is_demo=False,
            idempotency_key="buy-1",
        )
    store.close_position(
        portfolio_id=portfolio.id,
        symbol="TEST",
        market_price=108,
        reason="Zielnah",
        signal_score=55,
        provider="Test-Realdaten",
        is_demo=False,
        idempotency_key="sell-1",
        news_factor=0.3,
        news_ids=("exit-news-1",),
    )
    assert store.list_positions(portfolio.id) == []
    trades = store.list_trades(portfolio.id)
    assert len(trades) == 1
    assert trades[0].pnl_eur > 0
    assert trades[0].strategy_version == "v1"
    assert trades[0].weight_version == "v1"
    assert trades[0].entry_provider == "Test-Realdaten"
    assert trades[0].exit_provider == "Test-Realdaten"
    assert trades[0].entry_news_factor == 0.7
    assert trades[0].exit_news_factor == 0.3
    assert trades[0].entry_news_ids == "entry-news-1,entry-news-2"
    assert trades[0].exit_news_ids == "exit-news-1"
    assert trades[0].is_demo is False


def test_duplicate_symbol_and_reset_are_safe(store):
    portfolio = next(value for value in store.list_portfolios() if value.name == "Normal")
    arguments = {
        "portfolio_id": portfolio.id,
        "symbol": "TEST",
        "quantity": 1,
        "market_price": 100,
        "stop_loss": 90,
        "take_profit": 120,
        "reason": "Test",
        "signal_score": 70,
        "weight_version": "v1",
        "provider": "Test-Realdaten",
        "is_demo": False,
    }
    store.open_position(**arguments)
    with pytest.raises(PortfolioError, match="Nachkauf"):
        store.open_position(**arguments)
    store.reset_portfolio(portfolio.id, 12_000)
    assert store.list_positions(portfolio.id) == []
    refreshed = store.get_portfolio(portfolio.id)
    assert refreshed.cash == refreshed.initial_capital == 12_000


def test_daily_loss_limit_blocks_new_virtual_trades(store):
    portfolio = next(value for value in store.list_portfolios() if value.name == "Normal")
    store.open_position(
        portfolio_id=portfolio.id,
        symbol="LOSS",
        quantity=10,
        market_price=100,
        stop_loss=90,
        take_profit=120,
        reason="Risikotest",
        signal_score=70,
        weight_version="v1",
        provider="Test-Realdaten",
        is_demo=False,
    )
    store.close_position(
        portfolio_id=portfolio.id,
        symbol="LOSS",
        market_price=70,
        reason="Testverlust",
        signal_score=20,
        provider="Test-Realdaten",
        is_demo=False,
    )
    allowed, reason = store.trading_guard(portfolio.id)
    assert not allowed
    assert "Verlustlimit" in reason


def test_demo_and_real_sources_cannot_be_mixed(store):
    portfolio = next(value for value in store.list_portfolios() if value.name == "Normal")
    store.open_position(
        portfolio_id=portfolio.id,
        symbol="MIX",
        quantity=2,
        market_price=50,
        stop_loss=45,
        take_profit=60,
        reason="Quellentest",
        signal_score=70,
        weight_version="v1",
        provider="Offline-Testdaten",
        is_demo=True,
    )
    with pytest.raises(PortfolioError, match="Demo- und Realdaten"):
        store.close_position(
            portfolio_id=portfolio.id,
            symbol="MIX",
            market_price=500,
            reason="Darf nicht gebucht werden",
            signal_score=50,
            provider="yfinance",
            is_demo=False,
        )
    assert len(store.list_positions(portfolio.id)) == 1
    assert store.list_trades(portfolio.id) == []


def test_large_jump_during_real_source_switch_is_blocked(store):
    portfolio = next(value for value in store.list_portfolios() if value.name == "Normal")
    store.open_position(
        portfolio_id=portfolio.id,
        symbol="JUMP",
        quantity=2,
        market_price=50,
        stop_loss=45,
        take_profit=60,
        reason="Quellentest",
        signal_score=70,
        weight_version="v1",
        provider="yfinance",
        is_demo=False,
    )
    with pytest.raises(PortfolioError, match="Kurssprung"):
        store.update_market_price(
            portfolio.id,
            "JUMP",
            500,
            provider="Stooq (Tagesschluss)",
            is_demo=False,
        )
