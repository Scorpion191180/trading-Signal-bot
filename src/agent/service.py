"""Autonomer Analyse-Agent; kann ausschließlich virtuelle Orders erzeugen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.analysis.indicators import add_indicators
from src.analysis.signals import SignalAction, analyze_signal
from src.config import STRATEGIES, AppSettings
from src.data.base import MarketDataProvider, MarketDataRequest
from src.database.repositories import DataStore, DuplicateOrderError, PortfolioError
from src.portfolio.risk import calculate_position_size


@dataclass(frozen=True)
class AgentRunResult:
    run_id: int | None
    signals: int
    virtual_actions: int
    errors: tuple[str, ...]
    skipped_duplicate: bool = False


class TradingAgent:
    """Verbindet Daten, Regeln, Risikoschutz und getrennte Spielgeld-Depots."""

    def __init__(self, provider: MarketDataProvider, store: DataStore, settings: AppSettings) -> None:
        self.provider = provider
        self.store = store
        self.settings = settings

    @staticmethod
    def current_run_key(now: datetime | None = None) -> str:
        current = now or datetime.now(UTC)
        slot_minute = (current.minute // 30) * 30
        return current.replace(minute=slot_minute, second=0, microsecond=0).isoformat()

    def run(self, *, force: bool = False) -> AgentRunResult:
        watchlist = self.store.list_watchlist()
        symbols = [item.symbol for item in watchlist]
        key = self.current_run_key()
        if force:
            key = f"{key}-{datetime.now(UTC).timestamp()}"
        try:
            run = self.store.start_agent_run(key, symbols, self.provider.name)
        except DuplicateOrderError:
            return AgentRunResult(None, 0, 0, (), skipped_duplicate=True)
        signal_count = 0
        action_count = 0
        errors: list[str] = []
        portfolios = {portfolio.strategy: portfolio for portfolio in self.store.list_portfolios()}
        for item in watchlist:
            try:
                frame = self.provider.history(
                    MarketDataRequest(
                        symbol=item.symbol,
                        interval=item.interval,
                        period="1y" if item.interval == "1d" else "5d",
                        prepost=item.extended_hours,
                    )
                )
                indicators = add_indicators(frame)
                relative_volume = float(indicators["relative_volume"].iloc[-1])
                for profile in STRATEGIES.values():
                    signal = analyze_signal(
                        item.symbol,
                        frame,
                        profile,
                        provider=self.provider.name,
                        stale_after_minutes=96 * 60 if item.interval == "1d" else self.settings.stale_after_minutes,
                    )
                    self.store.record_signal(signal)
                    signal_count += 1
                    portfolio = portfolios[profile.name]
                    positions = self.store.list_positions(portfolio.id)
                    position = next((value for value in positions if value.symbol == item.symbol), None)
                    if position:
                        self.store.update_market_price(portfolio.id, item.symbol, signal.price)
                        exit_reason = None
                        if signal.price <= position.stop_loss:
                            exit_reason = "Stop-Loss erreicht"
                        elif signal.price >= position.take_profit:
                            exit_reason = "Take-Profit erreicht"
                        elif signal.action is SignalAction.SELL:
                            exit_reason = "Regelbasiertes Verkaufssignal"
                        if exit_reason:
                            self.store.close_position(
                                portfolio_id=portfolio.id,
                                symbol=item.symbol,
                                market_price=signal.price,
                                reason=exit_reason,
                                signal_score=signal.score,
                                idempotency_key=f"{key}:{profile.name}:{item.symbol}:SELL",
                            )
                            action_count += 1
                    elif item.trading_allowed and signal.action is SignalAction.BUY:
                        guard_allowed, _ = self.store.trading_guard(portfolio.id)
                        portfolio_value = self.store.portfolio_value(portfolio.id)
                        decision = calculate_position_size(
                            portfolio_value=portfolio_value,
                            available_cash=portfolio.cash,
                            entry_price=signal.price,
                            stop_loss=signal.stop_loss or 0.0,
                            profile=profile,
                            open_positions=len(positions),
                            relative_volume=relative_volume,
                            data_is_fresh=signal.data_problem is None,
                            spread_pct=self.settings.spread_pct,
                        )
                        if guard_allowed and decision.allowed and signal.target_1:
                            self.store.open_position(
                                portfolio_id=portfolio.id,
                                symbol=item.symbol,
                                quantity=decision.quantity,
                                market_price=signal.price,
                                stop_loss=signal.stop_loss or 0.0,
                                take_profit=signal.target_1,
                                reason="Regelbasiertes Kaufsignal: " + "; ".join(signal.positive_factors[:3]),
                                signal_score=signal.score,
                                weight_version=signal.weight_version,
                                idempotency_key=f"{key}:{profile.name}:{item.symbol}:BUY",
                            )
                            action_count += 1
            except (ValueError, PortfolioError, RuntimeError) as exc:
                errors.append(f"{item.symbol}: {exc}")
        self.store.finish_agent_run(run.id, signal_count, action_count, errors)
        return AgentRunResult(run.id, signal_count, action_count, tuple(errors))
