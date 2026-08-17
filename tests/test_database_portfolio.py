from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.database.models import FocusForecastOutcome, StrategyVersion, WeightVersion
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


def test_focus_bot_status_is_a_single_updatable_heartbeat(store):
    first = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    created = store.update_focus_bot_status(
        bot_key="dwave-paper",
        run_state="ACTIVE",
        signal_action="WAIT",
        signal_score=50.0,
        account_state="CASH",
        message="erster Zyklus",
        heartbeat_at=first,
    )
    updated = store.update_focus_bot_status(
        bot_key="dwave-paper",
        run_state="ACTIVE",
        signal_action="BUY",
        signal_score=72.0,
        account_state="INVESTIERT",
        message="Kaufsignal",
        heartbeat_at=first + timedelta(seconds=10),
        quote_at=first + timedelta(seconds=9),
    )

    status = store.get_focus_bot_status()
    assert status is not None
    assert created.id == updated.id == status.id
    assert status.signal_action == "BUY"
    assert status.account_state == "INVESTIERT"
    assert status.message == "Kaufsignal"
    assert status.last_quote_at is not None


def test_focus_forecast_is_deduplicated_and_only_resolved_with_future_prices(store):
    forecast_at = datetime(2026, 8, 13, 8, 1, tzinfo=UTC)
    arguments = {
        "symbol": "RQ0",
        "provider": "Lang & Schwarz",
        "forecast_at": forecast_at,
        "entry_price": 10.0,
        "bid": 9.99,
        "ask": 10.01,
        "direction": "EHER STEIGEND",
        "model_score": 64.0,
        "forecast_low": 9.8,
        "forecast_high": 10.2,
        "market_regime": "Trend",
        "strategy_votes": ("Trend 70 ↑", "Momentum 65 ↑"),
        "spread_percent": 0.2,
        "horizon_forecasts": tuple(
            {
                "minutes": minutes,
                "direction": direction,
                "expected_price": expected,
                "expected_low": expected - 0.1,
                "expected_high": expected + 0.1,
                "confidence": 70.0,
            }
            for minutes, direction, expected in (
                (5, "STEIGEND", 10.03),
                (15, "STEIGEND", 10.10),
                (30, "STEIGEND", 10.20),
                (60, "FALLEND", 9.50),
                (120, "SEITWÄRTS", 10.00),
            )
        ),
    }
    forecast, inserted = store.record_focus_forecast(**arguments)
    duplicate, duplicate_inserted = store.record_focus_forecast(
        **{**arguments, "forecast_at": forecast_at + timedelta(minutes=3)}
    )

    assert inserted is True
    assert duplicate_inserted is False
    assert duplicate.id == forecast.id
    assert len(store.list_focus_forecasts()) == 1
    assert store.evaluate_focus_forecasts(
        "RQ0",
        [(forecast_at + timedelta(minutes=4), 10.5)],
    ) == 0
    assert store.evaluate_focus_forecasts(
        "RQ0",
        [(forecast_at + timedelta(minutes=5), 10.5)],
        provider="Tradegate BSX",
    ) == 0

    resolved = store.evaluate_focus_forecasts(
        "RQ0",
        [
            (forecast_at + timedelta(minutes=5), 10.03),
            (forecast_at + timedelta(minutes=15), 10.10),
            (forecast_at + timedelta(minutes=30), 10.30),
            (forecast_at + timedelta(minutes=60), 9.50),
            (forecast_at + timedelta(minutes=120), 10.00),
        ],
        provider="Lang & Schwarz",
    )

    assert resolved == 5
    metrics = store.focus_forecast_metrics(symbol="RQ0", horizon_minutes=15)
    assert metrics["recorded"] == 1
    assert metrics["completed"] == 1
    assert metrics["direction_accuracy"] == 100.0
    assert metrics["zone_coverage"] == 100.0
    assert metrics["average_return"] == pytest.approx(1.0)
    with store.sessions() as session:
        outcomes = list(session.scalars(select(FocusForecastOutcome)))
    assert len(outcomes) == 5
    assert next(item for item in outcomes if item.horizon_minutes == 30).zone_hit is False
    sixty_minute = store.focus_forecast_chart_points(symbol="RQ0", horizon_minutes=60)
    assert len(sixty_minute) == 1
    assert sixty_minute[0]["expected_price"] == 9.5
    assert sixty_minute[0]["observed_price"] == 9.5
    assert sixty_minute[0]["direction_hit"] is True


def test_focus_forecast_metrics_keep_strategy_versions_separate(store):
    forecast_at = datetime(2026, 8, 13, 8, 1, tzinfo=UTC)
    arguments = {
        "symbol": "RQ0",
        "provider": "Lang & Schwarz",
        "forecast_at": forecast_at,
        "entry_price": 10.0,
        "bid": 9.99,
        "ask": 10.01,
        "direction": "EHER STEIGEND",
        "model_score": 64.0,
        "forecast_low": 9.8,
        "forecast_high": 10.2,
        "market_regime": "Trend",
        "strategy_votes": ("Trend 70 ↑",),
        "spread_percent": 0.2,
        "horizon_forecasts": (
            {
                "minutes": 15,
                "direction": "STEIGEND",
                "expected_price": 10.1,
                "expected_low": 9.9,
                "expected_high": 10.3,
                "confidence": 60.0,
            },
        ),
    }

    old, old_inserted = store.record_focus_forecast(**arguments, model_version="focus-market-v1")
    new, new_inserted = store.record_focus_forecast(**arguments, model_version="focus-market-v2")

    assert old_inserted is True
    assert new_inserted is True
    assert old.id != new.id
    assert store.focus_forecast_metrics(symbol="RQ0", model_version="focus-market-v1")["recorded"] == 1
    assert store.focus_forecast_metrics(symbol="RQ0", model_version="focus-market-v2")["recorded"] == 1
    assert len(store.focus_forecast_chart_points(model_version="focus-market-v2", horizon_minutes=15)) == 1
    assert len(
        store.focus_forecast_chart_points(
            model_version=("focus-market-v1", "focus-market-v2"),
            horizon_minutes=15,
        )
    ) == 2
    assert store.focus_forecast_chart_points(model_version="focus-market-v3", horizon_minutes=15) == []


def test_focus_forecast_direction_must_beat_recorded_spread(store):
    forecast_at = datetime(2026, 8, 13, 8, 1, tzinfo=UTC)
    store.record_focus_forecast(
        symbol="RQ0",
        provider="Lang & Schwarz",
        forecast_at=forecast_at,
        entry_price=10.0,
        bid=9.98,
        ask=10.02,
        direction="EHER STEIGEND",
        model_score=64.0,
        forecast_low=9.8,
        forecast_high=10.2,
        market_regime="Trend",
        strategy_votes=("Trend 70 ↑",),
        spread_percent=0.4,
        horizon_forecasts=(
            {
                "minutes": 5,
                "direction": "STEIGEND",
                "expected_price": 10.05,
                "expected_low": 9.9,
                "expected_high": 10.2,
                "confidence": 60.0,
            },
        ),
    )

    assert store.evaluate_focus_forecasts(
        "RQ0",
        [(forecast_at + timedelta(minutes=5), 10.02)],
        provider="Lang & Schwarz",
    ) == 1
    point = store.focus_forecast_chart_points(horizon_minutes=5)[0]
    assert point["direction_hit"] is False


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
    store.set_portfolio_active(portfolio.id, True)
    store.reset_portfolio(portfolio.id, 12_000, active=False)
    assert store.list_positions(portfolio.id) == []
    refreshed = store.get_portfolio(portfolio.id)
    assert refreshed.cash == refreshed.initial_capital == 12_000
    assert refreshed.active is False


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
