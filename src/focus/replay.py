"""Zeitlich sauberer Tages-Replay der D-Wave-Papierstrategie."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory

from .analysis import DWAVE_INSTRUMENT, analyze_timeframes, build_market_signal
from .data import resample_ohlcv
from .paper import PAPER_STARTING_CAPITAL, current_paper_account, run_paper_account
from .quote import LiveQuote, resample_intraday_candles
from .worker import _completed_candles

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class ReplayOrder:
    side: str
    executed_at: datetime
    quantity: float
    market_price: float
    execution_price: float
    costs: float
    reason: str


@dataclass(frozen=True)
class FocusReplayResult:
    trading_date: date
    first_candle_at: datetime
    last_candle_at: datetime
    initial_capital: float
    ending_equity: float
    pnl_eur: float
    pnl_percent: float
    gross_before_costs: float
    transaction_costs: float
    completed_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown_percent: float
    evaluated_minutes: int
    skipped_minutes: int
    buy_signal_minutes: int
    sell_signal_minutes: int
    open_position: bool
    market_change_percent: float
    average_spread_eur: float
    confirmation_observations: int
    rejected_entries: tuple[tuple[str, int], ...]
    orders: tuple[ReplayOrder, ...]


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _trading_day(frame: pd.DataFrame, selected_date: date | None) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("Für den Tages-Replay fehlen Minutenkerzen.")
    local_dates = frame.index.tz_convert(BERLIN).date
    trading_date = selected_date or local_dates[-1]
    selected = frame.loc[local_dates == trading_date].copy()
    if selected.empty:
        raise ValueError(f"Für {trading_date:%d.%m.%Y} liegen keine Minutenkerzen vor.")
    full_index = pd.date_range(selected.index[0], selected.index[-1], freq="1min", tz="UTC")
    selected = selected.reindex(full_index)
    selected["close"] = selected["close"].ffill().bfill()
    for column in ("open", "high", "low"):
        selected[column] = selected[column].fillna(selected["close"])
    selected["volume"] = selected["volume"].fillna(0.0)
    selected.index.name = "timestamp"
    return selected


def _ask_closes(ask_minutes: pd.DataFrame, bid_minutes: pd.DataFrame) -> pd.Series:
    ask = ask_minutes["close"].reindex(bid_minutes.index).ffill().bfill()
    if ask.isna().any():
        raise ValueError("Für den Tages-Replay fehlen historische L&S-Briefkurse.")
    return pd.Series(
        [
            max(float(ask_value), float(bid_value))
            for ask_value, bid_value in zip(ask, bid_minutes["close"], strict=True)
        ],
        index=bid_minutes.index,
        dtype=float,
    )


def _historical_frames(
    bid_minutes: pd.DataFrame,
    five_minutes: pd.DataFrame,
    hourly: pd.DataFrame,
    daily: pd.DataFrame,
    signal_at: datetime,
) -> dict[str, pd.DataFrame]:
    completed_five = _completed_candles(five_minutes, 300, signal_at)
    completed_fifteen = _completed_candles(
        resample_intraday_candles(completed_five, 15),
        900,
        signal_at,
    )
    completed_hourly = _completed_candles(hourly, 3600, signal_at)
    completed_daily = _completed_candles(daily, 86400, signal_at)
    return {
        "1m": bid_minutes,
        "5m": completed_five,
        "15m": completed_fifteen,
        "1h": completed_hourly,
        "1d": completed_daily,
        "1wk": resample_ohlcv(completed_daily, "W-FRI", drop_future_label=True),
        "1mo": resample_ohlcv(completed_daily, "ME", drop_future_label=True),
    }


def replay_focus_day(
    *,
    bid_minutes: pd.DataFrame,
    ask_minutes: pd.DataFrame,
    five_minutes: pd.DataFrame,
    hourly: pd.DataFrame,
    daily: pd.DataFrame,
    selected_date: date | None = None,
    confirmation_observations: int = 2,
) -> FocusReplayResult:
    """Spielt v2 Minute fuer Minute ohne Zugriff auf spaetere Kerzen durch."""

    if confirmation_observations < 1:
        raise ValueError("Die Zahl der Bestätigungsbeobachtungen muss positiv sein.")
    bid_day = _trading_day(bid_minutes, selected_date)
    ask_day = _trading_day(ask_minutes, selected_date)
    asks = _ask_closes(ask_day, bid_day)
    spreads = (asks - bid_day["close"]).clip(lower=0.0)
    engine = create_database("sqlite:///:memory:")
    settings = AppSettings(database_url="sqlite:///:memory:")
    store = DataStore(create_session_factory(engine), settings)
    account = current_paper_account(store, float(bid_day["close"].iloc[0]))
    confirmation_bucket: pd.Timestamp | None = None
    confirmation_cycles = 0
    evaluated = skipped = buy_signals = sell_signals = 0
    equity_peak = PAPER_STARTING_CAPITAL
    max_drawdown = 0.0
    rejected_entries: Counter[str] = Counter()

    try:
        for timestamp, candle in bid_day.iterrows():
            signal_at = (timestamp + timedelta(minutes=1)).to_pydatetime()
            minute_history = bid_day.loc[:timestamp].copy()
            minute_history.attrs.update(bid_minutes.attrs)
            frames = _historical_frames(
                minute_history,
                five_minutes,
                hourly,
                daily,
                signal_at,
            )
            analyses, enriched, errors = analyze_timeframes(frames)
            if errors:
                skipped += 1
                continue

            close_bid = float(candle["close"])
            spread = float(spreads.loc[timestamp])
            execution_bid = close_bid
            positions = store.list_positions(account.portfolio_id)
            if positions:
                position = positions[0]
                if float(candle["low"]) <= position.stop_loss:
                    execution_bid = min(float(candle["open"]), position.stop_loss)
                elif float(candle["high"]) >= position.take_profit:
                    execution_bid = max(float(candle["open"]), position.take_profit)
            quote = LiveQuote(
                provider="stock3 historischer L&S-Geld-/Briefkurs",
                venue="Lang & Schwarz",
                isin=DWAVE_INSTRUMENT.isin,
                bid=execution_bid,
                ask=execution_bid + spread,
                bid_size=None,
                ask_size=None,
                last=execution_bid,
                high=float(candle["high"]),
                low=float(candle["low"]),
                change_percent=None,
                volume=None,
                fetched_at=signal_at,
                quoted_at=signal_at,
                refresh_seconds=60,
            )
            signal = build_market_signal(
                analyses,
                enriched,
                now=signal_at,
                live_price=close_bid,
                session_close=time(23, 0),
                spread_percent=quote.spread_percent,
                order_imbalance=None,
                require_volume_confirmation=False,
                enforce_liquidity_filter=False,
            )
            evaluated += 1
            buy_signals += signal.action == "BUY"
            sell_signals += signal.action == "SELL"
            bucket = pd.Timestamp(signal_at).floor("5min")
            if signal.action != "BUY":
                confirmation_bucket = None
                confirmation_cycles = 0
            elif bucket != confirmation_bucket:
                confirmation_bucket = bucket
                confirmation_cycles = 1
            else:
                confirmation_cycles += 1
            had_position = account.quantity > 0
            account = run_paper_account(
                store,
                quote,
                signal,
                signal_at=signal_at,
                entry_confirmed=confirmation_cycles >= confirmation_observations,
            )
            if signal.action == "BUY" and not had_position and account.quantity <= 0:
                rejected_entries[account.state] += 1
            equity_peak = max(equity_peak, account.equity)
            if equity_peak > 0:
                max_drawdown = max(max_drawdown, (equity_peak - account.equity) / equity_peak * 100)

        final_bid = float(bid_day["close"].iloc[-1])
        account = current_paper_account(store, final_bid)
        trades = store.list_trades(account.portfolio_id)
        raw_orders = sorted(store.list_orders(account.portfolio_id, limit=1_000), key=lambda row: row.executed_at)
        orders = tuple(
            ReplayOrder(
                side=row.side,
                executed_at=_aware_utc(row.executed_at),
                quantity=float(row.quantity),
                market_price=float(row.market_price),
                execution_price=float(row.execution_price),
                costs=float(row.fees + row.spread_cost + row.slippage_cost),
                reason=row.reason,
            )
            for row in raw_orders
        )
        costs = account.total_transaction_costs
        return FocusReplayResult(
            trading_date=bid_day.index[-1].tz_convert(BERLIN).date(),
            first_candle_at=bid_day.index[0].to_pydatetime(),
            last_candle_at=bid_day.index[-1].to_pydatetime(),
            initial_capital=PAPER_STARTING_CAPITAL,
            ending_equity=account.equity,
            pnl_eur=account.result_eur,
            pnl_percent=account.result_percent,
            gross_before_costs=account.result_eur + costs,
            transaction_costs=costs,
            completed_trades=len(trades),
            winning_trades=sum(trade.pnl_eur > 0 for trade in trades),
            losing_trades=sum(trade.pnl_eur < 0 for trade in trades),
            max_drawdown_percent=max_drawdown,
            evaluated_minutes=evaluated,
            skipped_minutes=skipped,
            buy_signal_minutes=buy_signals,
            sell_signal_minutes=sell_signals,
            open_position=account.quantity > 0,
            market_change_percent=(final_bid / float(bid_day["close"].iloc[0]) - 1) * 100,
            average_spread_eur=float(spreads.mean()),
            confirmation_observations=confirmation_observations,
            rejected_entries=tuple(rejected_entries.most_common()),
            orders=orders,
        )
    finally:
        engine.dispose()
