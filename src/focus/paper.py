"""Eigenständiges 2.000-Euro-Papierkonto für das D-Wave-Marktsignal."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.database import DataStore
from src.database.models import Trade, VirtualPortfolio, VirtualPosition
from src.database.repositories import DuplicateOrderError, PortfolioError

from .analysis import (
    DWAVE_INSTRUMENT,
    MICROTREND_CONTINUATION_EVENT,
    PROFIT_EXHAUSTION_EVENT,
    US_OPENING_REVERSAL_EVENT,
    IntradaySignal,
)
from .quote import LiveQuote

PAPER_PORTFOLIO_NAME = "D-Wave Signal-Bot · 2.000 EUR"
PAPER_STARTING_CAPITAL = 2_000.0
TRADE_REPUBLIC_ORDER_FEE = 1.0
PAPER_SLIPPAGE_PCT = 0.0005
PAPER_MAX_SPREAD_PERCENT = 0.6
PAPER_STRATEGY_VERSION = "focus-market-v8"
PAPER_MAX_CAPITAL_FRACTION = 0.50
PAPER_RISK_PER_TRADE = 0.0075
PAPER_MIN_NET_EDGE_PCT = 0.002
PAPER_MIN_REWARD_RISK = 1.35
PAPER_MAX_TRADES_PER_DAY = 4
PAPER_MAX_CONSECUTIVE_LOSSES = 2
PAPER_DAILY_LOSS_LIMIT = 0.015
PAPER_COOLDOWN_MINUTES = 15
PAPER_STOP_COOLDOWN_MINUTES = 30
PAPER_MIN_SIGNAL_EXIT_MINUTES = 5
PAPER_TREND_REVIEW_MINUTES = 30
PAPER_MAX_HOLD_MINUTES = 120
BERLIN = ZoneInfo("Europe/Berlin")


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


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _execution_price(side: str, midpoint: float, spread_pct: float, slippage_pct: float) -> float:
    direction = 1 if side == "BUY" else -1
    return midpoint * (1 + direction * (spread_pct / 2 + slippage_pct))


def _exit_execution_at_bid(bid: float, quote: LiveQuote, spread_pct: float, slippage_pct: float) -> float:
    assumed_midpoint = bid + quote.spread / 2
    return _execution_price("SELL", assumed_midpoint, spread_pct, slippage_pct)


def _entry_plan(
    portfolio: VirtualPortfolio,
    quote: LiveQuote,
    signal: IntradaySignal,
) -> tuple[float, float, float] | str:
    """Prueft erst die Nettorendite und bestimmt dann eine risikobegrenzte Stueckzahl."""

    if signal.stop_loss is None or signal.target is None:
        return "WARTET · SCHUTZMARKEN"
    fee, spread_pct, slippage_pct = _execution_costs(quote)
    entry_execution = _execution_price("BUY", quote.midpoint, spread_pct, slippage_pct)
    target_execution = _exit_execution_at_bid(signal.target, quote, spread_pct, slippage_pct)
    stop_execution = _exit_execution_at_bid(signal.stop_loss, quote, spread_pct, slippage_pct)
    reward_per_share = target_execution - entry_execution
    risk_per_share = entry_execution - stop_execution
    if reward_per_share <= 0 or risk_per_share <= 0:
        return "WARTET · KOSTEN"

    equity = portfolio.cash
    capital_limit = min(portfolio.cash, equity * PAPER_MAX_CAPITAL_FRACTION)
    affordable_quantity = max((capital_limit - fee) / entry_execution, 0.0)
    loss_budget = max(equity * PAPER_RISK_PER_TRADE - 2 * fee, 0.0)
    risk_quantity = loss_budget / risk_per_share if risk_per_share > 0 else 0.0
    quantity = min(affordable_quantity, risk_quantity)
    if quantity <= 0:
        return "WARTET · RISIKOLIMIT"

    net_reward = reward_per_share * quantity - 2 * fee
    net_risk = risk_per_share * quantity + 2 * fee
    invested_value = entry_execution * quantity
    minimum_net_reward = invested_value * PAPER_MIN_NET_EDGE_PCT
    if net_reward < minimum_net_reward or net_reward / net_risk < PAPER_MIN_REWARD_RISK:
        return "WARTET · KOSTEN"
    return quantity, signal.stop_loss, signal.target


def _today_trades(store: DataStore, portfolio_id: int, signal_at: datetime) -> list[Trade]:
    trading_date = _aware_utc(signal_at).astimezone(BERLIN).date()
    result = []
    for trade in store.list_trades(portfolio_id):
        exit_time = _aware_utc(trade.exit_time)
        if exit_time.astimezone(BERLIN).date() == trading_date:
            result.append(trade)
    return result


def _entry_guard(store: DataStore, portfolio: VirtualPortfolio, signal_at: datetime) -> str | None:
    trades = _today_trades(store, portfolio.id, signal_at)
    if len(trades) >= PAPER_MAX_TRADES_PER_DAY:
        return "WARTET · TAGESLIMIT"
    if sum(float(trade.pnl_eur) for trade in trades) <= -portfolio.initial_capital * PAPER_DAILY_LOSS_LIMIT:
        return "WARTET · VERLUSTLIMIT"

    consecutive_losses = 0
    for trade in trades:
        if trade.pnl_eur < 0:
            consecutive_losses += 1
        else:
            break
    if consecutive_losses >= PAPER_MAX_CONSECUTIVE_LOSSES:
        return "WARTET · VERLUSTPAUSE"
    if trades:
        latest = trades[0]
        cooldown = PAPER_STOP_COOLDOWN_MINUTES if "Stop-Loss" in latest.exit_reason else PAPER_COOLDOWN_MINUTES
        if _aware_utc(signal_at) < _aware_utc(latest.exit_time) + timedelta(minutes=cooldown):
            return f"WARTET · {cooldown} MIN PAUSE"
    return None


def _trend_supports_extended_hold(
    signal: IntradaySignal,
    position: VirtualPosition,
    quote: LiveQuote,
) -> bool:
    """Verlängert nur profitable Positionen mit weiter positivem Trend und Kontext."""

    return bool(
        signal.action != "SELL"
        and signal.forecast_direction in {"EHER STEIGEND", "STEIGEND"}
        and signal.score >= 58
        and signal.external_context_score >= 35
        and quote.bid >= position.average_price
    )


def run_paper_account(
    store: DataStore,
    quote: LiveQuote,
    signal: IntradaySignal,
    *,
    signal_at: datetime,
    entry_confirmed: bool = True,
) -> PaperAccount:
    """Bucht nur neue Vorwärtssignale; vorhandene Chartgeschichte wird nie nachträglich gehandelt."""

    portfolio = _portfolio(store)
    position = _position(store, portfolio.id)
    provider = f"{quote.venue} · {quote.provider} · Trade-Republic-Kostenmodell"
    fee, spread_pct, slippage_pct = _execution_costs(quote)
    execution_allowed = signal.market_open and signal.data_age_minutes <= 4
    waiting_state: str | None = None
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
            if not entry_confirmed:
                waiting_state = "WARTET · BESTÄTIGUNG"
            else:
                waiting_state = _entry_guard(store, portfolio, signal_at)
            plan = _entry_plan(portfolio, quote, signal) if waiting_state is None else waiting_state
            if isinstance(plan, str):
                waiting_state = plan
            else:
                quantity, stop_loss, take_profit = plan
                entry_reason = (
                    "Bestätigtes KAUFEN · US-Eröffnungs-Reversal · Kostenhürde bestanden"
                    if signal.structure_event == US_OPENING_REVERSAL_EVENT
                    else "Bestätigtes KAUFEN · bullischer Mikrotrend · Kostenhürde bestanden"
                    if signal.structure_event == MICROTREND_CONTINUATION_EVENT
                    else "Bestätigtes KAUFEN · BOS/OTT/UT/LinReg · Kostenhürde bestanden"
                )
                store.open_position(
                    portfolio_id=portfolio.id,
                    symbol=DWAVE_INSTRUMENT.exchange_symbol,
                    quantity=quantity,
                    market_price=quote.midpoint,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason=entry_reason,
                    signal_score=signal.score,
                    weight_version=PAPER_STRATEGY_VERSION,
                    provider=provider,
                    is_demo=False,
                    idempotency_key=f"focus:{portfolio.id}:BUY:{_bucket(signal_at)}",
                    fee=fee,
                    spread_pct=spread_pct,
                    slippage_pct=slippage_pct,
                    executed_at=_aware_utc(signal_at),
                )
                store.update_market_price(
                    portfolio.id,
                    DWAVE_INSTRUMENT.exchange_symbol,
                    quote.bid,
                    provider=provider,
                    is_demo=False,
                )
        elif position is not None and signal.market_open:
            exit_reason = None
            held_minutes = (
                _aware_utc(signal_at) - _aware_utc(position.opened_at)
            ).total_seconds() / 60
            if quote.bid <= position.stop_loss:
                exit_reason = "Stop-Loss erreicht"
            elif quote.bid >= position.take_profit:
                exit_reason = "Kostenbereinigtes technisches Ziel erreicht"
            elif (
                execution_allowed
                and held_minutes >= PAPER_MIN_SIGNAL_EXIT_MINUTES
                and signal.action == "SELL"
                and signal.structure_event == PROFIT_EXHAUSTION_EVENT
                and quote.bid > position.average_price
            ):
                exit_reason = "Gewinnmitnahme · überkaufter Mikrotrend verliert Schwung"
            elif (
                execution_allowed
                and held_minutes >= PAPER_MIN_SIGNAL_EXIT_MINUTES
                and signal.action == "SELL"
                and signal.score <= 38
            ):
                exit_reason = "Bestätigtes VERKAUFEN · kurzfristiger Trend gekippt"
            elif held_minutes >= PAPER_MAX_HOLD_MINUTES:
                exit_reason = "Sicherheitszeitlimit 120 Minuten erreicht"
            elif held_minutes >= PAPER_TREND_REVIEW_MINUTES and not _trend_supports_extended_hold(
                signal,
                position,
                quote,
            ):
                exit_reason = "Adaptive Haltedauer · Trend nicht mehr ausreichend bestätigt"
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
                    executed_at=_aware_utc(signal_at),
                )
    except (DuplicateOrderError, PortfolioError):
        pass
    account = paper_account(store, portfolio.id, quote.bid)
    if waiting_state is not None:
        return replace(account, state=waiting_state)
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


def current_paper_account(store: DataStore, bid: float | None = None) -> PaperAccount:
    """Liest das Papierkonto, ohne eine Order auszulösen."""

    portfolio = _portfolio(store)
    position = _position(store, portfolio.id)
    current_bid = bid if bid is not None else position.current_price if position is not None else 0.0
    return paper_account(store, portfolio.id, current_bid)


def paper_order_events(
    store: DataStore,
    portfolio_id: int,
    trading_timestamp: pd.Timestamp,
) -> list[dict[str, object]]:
    trading_date = trading_timestamp.tz_convert("Europe/Berlin").date()
    day_orders = []
    for order in reversed(store.list_orders(portfolio_id, limit=100)):
        timestamp = pd.Timestamp(order.executed_at)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        if timestamp.tz_convert("Europe/Berlin").date() == trading_date:
            day_orders.append((order, timestamp))
    first_strategy_order = next(
        (
            index
            for index, (order, _timestamp) in enumerate(day_orders)
            if order.reason.startswith("Bestätigtes KAUFEN")
        ),
        None,
    )
    if first_strategy_order is None:
        return []
    events: list[dict[str, object]] = []
    for order, timestamp in day_orders[first_strategy_order:]:
        events.append(
            {
                "action": order.side,
                "price": order.execution_price,
                "timestamp": timestamp.isoformat(),
            }
        )
    return events
