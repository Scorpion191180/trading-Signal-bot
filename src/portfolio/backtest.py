"""Einfacher ereignisbasierter Backtest mit Ausführung auf der Folgekerze."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis.indicators import add_indicators
from src.config import StrategyProfile
from src.data.base import normalize_ohlcv

from .execution import simulated_execution
from .risk import calculate_position_size


@dataclass(frozen=True)
class BacktestTrade:
    entry_signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    reason: str


@dataclass(frozen=True)
class BacktestResult:
    initial_capital: float
    final_capital: float
    total_return_pct: float
    benchmark_return_pct: float
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    trades: tuple[BacktestTrade, ...]
    equity_curve: pd.DataFrame


def _score_row(row: pd.Series) -> float:
    checks = [
        row["close"] > row["ema_20"],
        row["ema_20"] > row["ema_50"],
        row["close"] > row["ema_200"],
        row["macd_hist"] > 0,
        45 <= row["rsi_14"] <= 70,
        row["relative_volume"] >= 0.8,
    ]
    return float(sum(bool(check) for check in checks) / len(checks) * 100)


def run_backtest(
    frame: pd.DataFrame,
    profile: StrategyProfile,
    *,
    initial_capital: float = 10_000.0,
    fee: float = 1.0,
    spread_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    """Handelt Signale frühestens am Open der nächsten Kerze und vermeidet Look-ahead-Bias."""

    if initial_capital <= 0:
        raise ValueError("Startkapital muss positiv sein.")
    data = add_indicators(normalize_ohlcv(frame)).dropna(subset=["ema_200", "atr_14", "relative_volume"])
    if len(data) < 3:
        raise ValueError("Für den Backtest werden mindestens 203 verwertbare Kerzen benötigt.")
    cash = initial_capital
    quantity = 0.0
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    entry_signal_time: pd.Timestamp | None = None
    stop = 0.0
    target = 0.0
    trades: list[BacktestTrade] = []
    equity_points: list[tuple[pd.Timestamp, float]] = []

    for index in range(1, len(data)):
        signal_row = data.iloc[index - 1]
        bar = data.iloc[index]
        signal_time = data.index[index - 1]
        execution_time = data.index[index]
        score = _score_row(signal_row)
        if quantity == 0 and score >= profile.buy_threshold:
            market_entry = float(bar["open"])
            proposed_stop = market_entry - profile.stop_atr * float(signal_row["atr_14"])
            decision = calculate_position_size(
                portfolio_value=cash,
                available_cash=cash,
                entry_price=market_entry,
                stop_loss=proposed_stop,
                profile=profile,
                open_positions=0,
                relative_volume=max(float(signal_row["relative_volume"]), profile.min_relative_volume),
                data_is_fresh=True,
                spread_pct=spread_pct,
            )
            if decision.allowed:
                quote = simulated_execution(
                    "BUY",
                    market_entry,
                    decision.quantity,
                    fee=fee,
                    spread_pct=spread_pct,
                    slippage_pct=slippage_pct,
                )
                if quote.gross_value + quote.fees <= cash:
                    quantity = quote.quantity
                    entry_price = quote.execution_price
                    entry_time = execution_time
                    entry_signal_time = signal_time
                    stop = proposed_stop
                    target = market_entry + profile.target_atr * float(signal_row["atr_14"])
                    cash -= quote.gross_value + quote.fees
        elif quantity > 0:
            exit_market: float | None = None
            reason = ""
            if float(bar["low"]) <= stop:
                exit_market, reason = min(float(bar["open"]), stop), "Stop-Loss"
            elif float(bar["high"]) >= target:
                exit_market, reason = max(float(bar["open"]), target), "Take-Profit"
            elif score <= profile.sell_threshold:
                exit_market, reason = float(bar["open"]), "Verkaufssignal"
            if exit_market is not None:
                quote = simulated_execution(
                    "SELL", exit_market, quantity, fee=fee, spread_pct=spread_pct, slippage_pct=slippage_pct
                )
                cash += quote.gross_value - quote.fees
                invested = entry_price * quantity + fee
                pnl = quote.gross_value - quote.fees - invested
                trades.append(
                    BacktestTrade(
                        entry_signal_time=entry_signal_time or signal_time,
                        entry_time=entry_time or execution_time,
                        exit_time=execution_time,
                        entry_price=entry_price,
                        exit_price=quote.execution_price,
                        quantity=quantity,
                        pnl=pnl,
                        reason=reason,
                    )
                )
                quantity = 0.0
        equity_points.append((execution_time, cash + quantity * float(bar["close"])))

    if quantity > 0:
        last_time = data.index[-1]
        quote = simulated_execution(
            "SELL", float(data["close"].iloc[-1]), quantity, fee=fee, spread_pct=spread_pct, slippage_pct=slippage_pct
        )
        cash += quote.gross_value - quote.fees
        pnl = quote.gross_value - quote.fees - (entry_price * quantity + fee)
        trades.append(
            BacktestTrade(
                entry_signal_time=entry_signal_time or last_time,
                entry_time=entry_time or last_time,
                exit_time=last_time,
                entry_price=entry_price,
                exit_price=quote.execution_price,
                quantity=quantity,
                pnl=pnl,
                reason="Backtest-Ende",
            )
        )
        equity_points.append((last_time, cash))
    equity = pd.DataFrame(equity_points, columns=["timestamp", "equity"]).drop_duplicates("timestamp", keep="last")
    equity = equity.set_index("timestamp")
    rolling_max = equity["equity"].cummax()
    drawdown = (equity["equity"] / rolling_max - 1) * 100
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    benchmark = (float(data["close"].iloc[-1]) / float(data["close"].iloc[0]) - 1) * 100
    return BacktestResult(
        initial_capital=initial_capital,
        final_capital=round(cash, 2),
        total_return_pct=round((cash / initial_capital - 1) * 100, 2),
        benchmark_return_pct=round(benchmark, 2),
        win_rate_pct=round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        profit_factor=round(profit_factor, 3) if np.isfinite(profit_factor) else profit_factor,
        max_drawdown_pct=round(abs(float(drawdown.min())), 2),
        trades=tuple(trades),
        equity_curve=equity,
    )
