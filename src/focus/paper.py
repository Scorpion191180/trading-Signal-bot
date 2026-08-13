"""Eigenständiges 2.000-Euro-Papierkonto für das D-Wave-Marktsignal."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pandas as pd

from src.database import DataStore
from src.database.models import VirtualPortfolio, VirtualPosition
from src.database.repositories import DuplicateOrderError, PortfolioError

from .analysis import DWAVE_INSTRUMENT, IntradaySignal
from .quote import LiveQuote

PAPER_PORTFOLIO_NAME = "D-Wave Signal-Bot · 2.000 EUR"
PAPER_STARTING_CAPITAL = 2_000.0
TRADE_REPUBLIC_ORDER_FEE = 1.0
PAPER_SLIPPAGE_PCT = 0.0005
PAPER_MAX_SPREAD_PERCENT = 0.6
PAPER_STRATEGY_VERSION = "focus-market-v1"


@dataclass(frozen=True)
class PaperAccount:
    portfolio_id: int
    initial_capital: float
    cash: float
    quantity: float
    average_price: float | None
    market_value: float
    equity: float
    result_eur: float
    result_percent: float
    state: str
    total_fees: float
    total_spread_cost: float
    total_slippage_cost: float
    total_transaction_costs: float
    completed_trades: int


def _portfolio(store: DataStore) -> VirtualPortfolio:
    return store.get_or_create_virtual_portfolio(
        name=PAPER_PORTFOLIO_NAME,
        strategy="D-Wave Kurzfrist-Marktsignal",
        strategy_version=PAPER_STRATEGY_VERSION,
        initial_capital=PAPER_STARTING_CAPITAL,
    )


def _position(store: DataStore, portfolio_id: int) -> VirtualPosition | None:
    return next(
        (
            item
            for item in store.list_positions(portfolio_id)
            if item.symbol == DWAVE_INSTRUMENT.exchange_symbol
        ),
        None,
    )


def _bucket(timestamp: datetime) -> str:
    value = timestamp.astimezone(UTC).replace(second=0, microsecond=0)
    return value.replace(minute=value.minute - value.minute % 5).strftime("%Y%m%dT%H%MZ")


def _execution_costs(quote: LiveQuote) -> tuple[float, float, float]:
    spread_pct = quote.spread / quote.midpoint
    return TRADE_REPUBLIC_ORDER_FEE, spread_pct, PAPER_SLIPPAGE_PCT


def _maximum_quantity(cash: float, quote: LiveQuote) -> float:
    fee, spread_pct, slippage_pct = _execution_costs(quote)
    execution_price = quote.midpoint * (1 + spread_pct / 2 + slippage_pct)
    return max((cash - fee) / execution_price, 0.0)


def run_paper_account(
    store: DataStore,
    quote: LiveQuote,
    signal: IntradaySignal,
    *,
    signal_at: datetime,
) -> PaperAccount:
    """Bucht nur neue Vorwärtssignale; vorhandene Chartgeschichte wird nie nachträglich gehandelt."""

    portfolio = _portfolio(store)
    position = _position(store, portfolio.id)
    provider = f"{quote.venue} · {quote.provider} · Trade-Republic-Kostenmodell"
    fee, spread_pct, slippage_pct = _execution_costs(quote)
    execution_allowed = signal.market_open and signal.data_age_minutes <= 4
    if position is not None:
        store.update_market_price(
            portfolio.id,
            DWAVE_INSTRUMENT.exchange_symbol,
            quote.bid,
            provider=provider,
            is_demo=False,
        )
        position = _position(store, portfolio.id)

    try:
        if (
            position is None
            and signal.action == "BUY"
            and execution_allowed
            and quote.spread_percent <= PAPER_MAX_SPREAD_PERCENT
            and signal.stop_loss
            and signal.target
        ):
            quantity = _maximum_quantity(portfolio.cash, quote)
            if quantity > 0:
                store.open_position(
                    portfolio_id=portfolio.id,
                    symbol=DWAVE_INSTRUMENT.exchange_symbol,
                    quantity=quantity,
                    market_price=quote.midpoint,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.target,
                    reason="Neutrales KAUFEN-Signal · 5–30 Minuten",
                    signal_score=signal.score,
                    weight_version=PAPER_STRATEGY_VERSION,
                    provider=provider,
                    is_demo=False,
                    idempotency_key=f"focus:{portfolio.id}:BUY:{_bucket(signal_at)}",
                    fee=fee,
                    spread_pct=spread_pct,
                    slippage_pct=slippage_pct,
                )
                store.update_market_price(
                    portfolio.id,
                    DWAVE_INSTRUMENT.exchange_symbol,
                    quote.bid,
                    provider=provider,
                    is_demo=False,
                )
        elif position is not None and execution_allowed:
            exit_reason = None
            if quote.bid <= position.stop_loss:
                exit_reason = "Stop-Loss erreicht"
            elif quote.bid >= position.take_profit:
                exit_reason = "Technisches Ziel erreicht"
            elif signal.action == "SELL":
                exit_reason = "Neutrales VERKAUFEN-Signal · kurzfristiger Trend gekippt"
            if exit_reason:
                store.close_position(
                    portfolio_id=portfolio.id,
                    symbol=DWAVE_INSTRUMENT.exchange_symbol,
                    market_price=quote.midpoint,
                    reason=exit_reason,
                    signal_score=signal.score,
                    provider=provider,
                    is_demo=False,
                    idempotency_key=f"focus:{portfolio.id}:SELL:{_bucket(signal_at)}",
                    fee=fee,
                    spread_pct=spread_pct,
                    slippage_pct=slippage_pct,
                )
    except (DuplicateOrderError, PortfolioError):
        pass
    account = paper_account(store, portfolio.id, quote.bid)
    if position is None and signal.action == "BUY" and quote.spread_percent > PAPER_MAX_SPREAD_PERCENT:
        return replace(account, state="WARTET · SPREAD")
    return account


def paper_account(store: DataStore, portfolio_id: int, bid: float) -> PaperAccount:
    portfolio = store.get_portfolio(portfolio_id)
    position = _position(store, portfolio_id)
    orders = store.list_orders(portfolio_id, limit=1_000)
    trades = store.list_trades(portfolio_id)
    quantity = position.quantity if position else 0.0
    market_value = quantity * bid
    equity = portfolio.cash + market_value
    result_eur = equity - portfolio.initial_capital
    total_fees = sum(order.fees for order in orders)
    total_spread_cost = sum(order.spread_cost for order in orders)
    total_slippage_cost = sum(order.slippage_cost for order in orders)
    return PaperAccount(
        portfolio_id=portfolio.id,
        initial_capital=portfolio.initial_capital,
        cash=portfolio.cash,
        quantity=quantity,
        average_price=position.average_price if position else None,
        market_value=market_value,
        equity=equity,
        result_eur=result_eur,
        result_percent=(result_eur / portfolio.initial_capital * 100),
        state="INVESTIERT" if position else "CASH",
        total_fees=total_fees,
        total_spread_cost=total_spread_cost,
        total_slippage_cost=total_slippage_cost,
        total_transaction_costs=total_fees + total_spread_cost + total_slippage_cost,
        completed_trades=len(trades),
    )


def paper_order_events(
    store: DataStore,
    portfolio_id: int,
    trading_timestamp: pd.Timestamp,
) -> list[dict[str, object]]:
    trading_date = trading_timestamp.tz_convert("Europe/Berlin").date()
    events: list[dict[str, object]] = []
    for order in reversed(store.list_orders(portfolio_id, limit=100)):
        timestamp = pd.Timestamp(order.executed_at)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        if timestamp.tz_convert("Europe/Berlin").date() != trading_date:
            continue
        events.append(
            {
                "action": order.side,
                "price": order.execution_price,
                "timestamp": timestamp.isoformat(),
            }
        )
    return events
