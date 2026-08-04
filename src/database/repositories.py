"""Transaktionale Anwendungsoperationen auf dem Datenmodell."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.analysis.signals import SignalResult
from src.config import STRATEGIES, WEIGHTS, AppSettings
from src.portfolio.execution import simulated_execution

from .models import (
    AgentRun,
    RealPosition,
    SignalRecord,
    StrategyVersion,
    Trade,
    VirtualOrder,
    VirtualPortfolio,
    VirtualPosition,
    WatchlistItem,
    WeightVersion,
)


class PortfolioError(RuntimeError):
    pass


class DuplicateOrderError(PortfolioError):
    pass


class DataStore:
    """Kleine Repository-Fassade; jede Methode besitzt eine klare Transaktion."""

    def __init__(self, session_factory: sessionmaker[Session], settings: AppSettings) -> None:
        self.sessions = session_factory
        self.settings = settings

    def seed_defaults(self) -> None:
        with self.sessions.begin() as session:
            existing_symbols = set(session.scalars(select(WatchlistItem.symbol)).all())
            for symbol in self.settings.default_symbols:
                if symbol not in existing_symbols:
                    session.add(WatchlistItem(symbol=symbol, company=symbol, analysis_only=True))
            for profile in STRATEGIES.values():
                exists = session.scalar(
                    select(StrategyVersion).where(
                        StrategyVersion.name == profile.name,
                        StrategyVersion.version == profile.version,
                    )
                )
                if not exists:
                    session.add(
                        StrategyVersion(
                            name=profile.name,
                            version=profile.version,
                            configuration_json=json.dumps(asdict(profile), ensure_ascii=False, sort_keys=True),
                        )
                    )
                portfolio = session.scalar(select(VirtualPortfolio).where(VirtualPortfolio.name == profile.name))
                if not portfolio:
                    session.add(
                        VirtualPortfolio(
                            name=profile.name,
                            strategy=profile.name,
                            strategy_version=profile.version,
                            initial_capital=self.settings.starting_capital,
                            cash=self.settings.starting_capital,
                        )
                    )
            if not session.scalar(select(WeightVersion).where(WeightVersion.version == WEIGHTS.version)):
                session.add(
                    WeightVersion(
                        version=WEIGHTS.version,
                        configuration_json=json.dumps(WEIGHTS.as_dict(), ensure_ascii=False, sort_keys=True),
                    )
                )

    def list_watchlist(self) -> list[WatchlistItem]:
        with self.sessions() as session:
            return list(session.scalars(select(WatchlistItem).order_by(WatchlistItem.priority.desc(), WatchlistItem.symbol)))

    def add_watchlist_item(
        self,
        symbol: str,
        *,
        company: str = "",
        priority: bool = False,
        trading_allowed: bool = False,
        interval: str = "5m",
        extended_hours: bool = False,
    ) -> WatchlistItem:
        normalized = symbol.upper().strip()
        if not normalized or len(normalized) > 20:
            raise ValueError("Bitte ein gültiges Tickersymbol angeben.")
        with self.sessions.begin() as session:
            item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == normalized))
            if item:
                item.company = company.strip() or item.company
                item.priority = priority
                item.trading_allowed = trading_allowed
                item.analysis_only = not trading_allowed
                item.interval = interval
                item.extended_hours = extended_hours
            else:
                item = WatchlistItem(
                    symbol=normalized,
                    company=company.strip() or normalized,
                    priority=priority,
                    trading_allowed=trading_allowed,
                    analysis_only=not trading_allowed,
                    interval=interval,
                    extended_hours=extended_hours,
                )
                session.add(item)
            session.flush()
            return item

    def delete_watchlist_item(self, item_id: int) -> None:
        with self.sessions.begin() as session:
            item = session.get(WatchlistItem, item_id)
            if item:
                session.delete(item)

    def update_watchlist_settings(
        self,
        item_id: int,
        *,
        priority: bool,
        trading_allowed: bool,
        interval: str,
        extended_hours: bool,
    ) -> WatchlistItem:
        """Speichert die direkt bedienbaren Einstellungen eines Watchlist-Eintrags."""

        if interval not in {"1m", "5m", "15m", "30m", "1h", "1d"}:
            raise ValueError("Das gewählte Analyseintervall wird nicht unterstützt.")
        with self.sessions.begin() as session:
            item = session.get(WatchlistItem, item_id)
            if item is None:
                raise ValueError("Der Watchlist-Eintrag wurde nicht gefunden.")
            item.priority = priority
            item.trading_allowed = trading_allowed
            item.analysis_only = not trading_allowed
            item.interval = interval
            item.extended_hours = extended_hours
            session.flush()
            return item

    def list_real_positions(self) -> list[RealPosition]:
        with self.sessions() as session:
            return list(session.scalars(select(RealPosition).order_by(RealPosition.symbol)))

    def add_real_position(
        self,
        *,
        company: str,
        symbol: str,
        quantity: float,
        average_price: float,
        purchase_date: date | None = None,
        currency: str = "EUR",
        isin_wkn: str | None = None,
        reference_market: str | None = None,
        stop_loss: float | None = None,
        target_price: float | None = None,
        notes: str = "",
    ) -> RealPosition:
        if quantity <= 0 or average_price <= 0:
            raise ValueError("Stückzahl und durchschnittlicher Kaufkurs müssen positiv sein.")
        with self.sessions.begin() as session:
            position = RealPosition(
                company=company.strip() or symbol.upper().strip(),
                symbol=symbol.upper().strip(),
                quantity=quantity,
                average_price=average_price,
                purchase_date=purchase_date,
                currency=currency.upper().strip(),
                isin_wkn=isin_wkn or None,
                reference_market=reference_market or None,
                stop_loss=stop_loss,
                target_price=target_price,
                notes=notes,
            )
            session.add(position)
            session.flush()
            return position

    def delete_real_position(self, position_id: int) -> None:
        with self.sessions.begin() as session:
            position = session.get(RealPosition, position_id)
            if position:
                session.delete(position)

    def list_portfolios(self) -> list[VirtualPortfolio]:
        with self.sessions() as session:
            return list(session.scalars(select(VirtualPortfolio).order_by(VirtualPortfolio.name)))

    def get_portfolio(self, portfolio_id: int) -> VirtualPortfolio:
        with self.sessions() as session:
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            if portfolio is None:
                raise PortfolioError("Virtuelles Depot nicht gefunden.")
            return portfolio

    def list_positions(self, portfolio_id: int | None = None) -> list[VirtualPosition]:
        with self.sessions() as session:
            query = select(VirtualPosition).order_by(VirtualPosition.symbol)
            if portfolio_id is not None:
                query = query.where(VirtualPosition.portfolio_id == portfolio_id)
            return list(session.scalars(query))

    def update_market_price(self, portfolio_id: int, symbol: str, price: float) -> None:
        with self.sessions.begin() as session:
            position = session.scalar(
                select(VirtualPosition).where(
                    VirtualPosition.portfolio_id == portfolio_id,
                    VirtualPosition.symbol == symbol.upper(),
                )
            )
            if position and price > 0:
                position.current_price = price

    def portfolio_value(self, portfolio_id: int) -> float:
        with self.sessions() as session:
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            if not portfolio:
                raise PortfolioError("Virtuelles Depot nicht gefunden.")
            positions_value = session.scalar(
                select(func.coalesce(func.sum(VirtualPosition.quantity * VirtualPosition.current_price), 0.0)).where(
                    VirtualPosition.portfolio_id == portfolio_id
                )
            )
            return float(portfolio.cash + (positions_value or 0.0))

    def open_position(
        self,
        *,
        portfolio_id: int,
        symbol: str,
        quantity: float,
        market_price: float,
        stop_loss: float,
        take_profit: float,
        reason: str,
        signal_score: float,
        weight_version: str,
        idempotency_key: str | None = None,
    ) -> VirtualOrder:
        key = idempotency_key or str(uuid.uuid4())
        with self.sessions.begin() as session:
            if session.scalar(select(VirtualOrder).where(VirtualOrder.idempotency_key == key)):
                raise DuplicateOrderError("Diese virtuelle Order wurde bereits verarbeitet.")
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            if portfolio is None:
                raise PortfolioError("Virtuelles Depot nicht gefunden.")
            normalized = symbol.upper().strip()
            if session.scalar(
                select(VirtualPosition).where(
                    VirtualPosition.portfolio_id == portfolio_id,
                    VirtualPosition.symbol == normalized,
                )
            ):
                raise PortfolioError("Für dieses Symbol besteht bereits eine Position; Nachkauf ist im MVP gesperrt.")
            quote = simulated_execution(
                "BUY",
                market_price,
                quantity,
                fee=self.settings.order_fee,
                spread_pct=self.settings.spread_pct,
                slippage_pct=self.settings.slippage_pct,
            )
            total = quote.gross_value + quote.fees
            if total > portfolio.cash:
                raise PortfolioError("Nicht genügend freies Spielgeld.")
            if not (stop_loss < quote.execution_price < take_profit):
                raise PortfolioError("Stop-Loss und Take-Profit sind für einen Kauf unplausibel.")
            portfolio.cash -= total
            order = VirtualOrder(
                idempotency_key=key,
                portfolio_id=portfolio_id,
                symbol=normalized,
                side="BUY",
                quantity=quote.quantity,
                market_price=quote.market_price,
                execution_price=quote.execution_price,
                gross_value=quote.gross_value,
                fees=quote.fees,
                spread_cost=quote.spread_cost,
                slippage_cost=quote.slippage_cost,
                reason=reason,
                signal_score=signal_score,
            )
            session.add(order)
            session.add(
                VirtualPosition(
                    portfolio_id=portfolio_id,
                    symbol=normalized,
                    quantity=quote.quantity,
                    average_price=quote.execution_price,
                    entry_fees_remaining=quote.fees,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    current_price=market_price,
                    entry_reason=reason,
                    entry_score=signal_score,
                    weight_version=weight_version,
                )
            )
            session.flush()
            return order

    def close_position(
        self,
        *,
        portfolio_id: int,
        symbol: str,
        market_price: float,
        reason: str,
        signal_score: float,
        quantity: float | None = None,
        idempotency_key: str | None = None,
    ) -> VirtualOrder:
        key = idempotency_key or str(uuid.uuid4())
        with self.sessions.begin() as session:
            if session.scalar(select(VirtualOrder).where(VirtualOrder.idempotency_key == key)):
                raise DuplicateOrderError("Diese virtuelle Order wurde bereits verarbeitet.")
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            position = session.scalar(
                select(VirtualPosition).where(
                    VirtualPosition.portfolio_id == portfolio_id,
                    VirtualPosition.symbol == symbol.upper().strip(),
                )
            )
            if not portfolio or not position:
                raise PortfolioError("Offene virtuelle Position nicht gefunden.")
            sell_quantity = position.quantity if quantity is None else quantity
            if sell_quantity <= 0 or sell_quantity > position.quantity + 1e-9:
                raise PortfolioError("Ungültige Verkaufsstückzahl.")
            quote = simulated_execution(
                "SELL",
                market_price,
                sell_quantity,
                fee=self.settings.order_fee,
                spread_pct=self.settings.spread_pct,
                slippage_pct=self.settings.slippage_pct,
            )
            entry_fee_share = position.entry_fees_remaining * (sell_quantity / position.quantity)
            proceeds = quote.gross_value - quote.fees
            portfolio.cash += proceeds
            cost_basis = position.average_price * sell_quantity + entry_fee_share
            pnl = proceeds - cost_basis
            pnl_pct = pnl / cost_basis * 100 if cost_basis else 0.0
            order = VirtualOrder(
                idempotency_key=key,
                portfolio_id=portfolio_id,
                symbol=position.symbol,
                side="SELL",
                quantity=sell_quantity,
                market_price=quote.market_price,
                execution_price=quote.execution_price,
                gross_value=quote.gross_value,
                fees=quote.fees,
                spread_cost=quote.spread_cost,
                slippage_cost=quote.slippage_cost,
                reason=reason,
                signal_score=signal_score,
            )
            session.add(order)
            session.add(
                Trade(
                    portfolio_id=portfolio_id,
                    strategy=portfolio.strategy,
                    strategy_version=portfolio.strategy_version,
                    weight_version=position.weight_version,
                    symbol=position.symbol,
                    entry_price=position.average_price,
                    entry_time=position.opened_at,
                    exit_price=quote.execution_price,
                    quantity=sell_quantity,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    pnl_eur=pnl,
                    pnl_pct=pnl_pct,
                    fees=entry_fee_share + quote.fees,
                    slippage=quote.slippage_cost,
                    entry_reason=position.entry_reason,
                    exit_reason=reason,
                    entry_score=position.entry_score,
                    exit_score=signal_score,
                )
            )
            position.quantity -= sell_quantity
            position.entry_fees_remaining -= entry_fee_share
            position.current_price = market_price
            if position.quantity <= 1e-9:
                session.delete(position)
            session.flush()
            return order

    def reset_portfolio(self, portfolio_id: int, initial_capital: float) -> None:
        if initial_capital <= 0:
            raise ValueError("Startkapital muss positiv sein.")
        with self.sessions.begin() as session:
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            if portfolio is None:
                raise PortfolioError("Virtuelles Depot nicht gefunden.")
            session.execute(delete(Trade).where(Trade.portfolio_id == portfolio_id))
            session.execute(delete(VirtualOrder).where(VirtualOrder.portfolio_id == portfolio_id))
            session.execute(delete(VirtualPosition).where(VirtualPosition.portfolio_id == portfolio_id))
            portfolio.initial_capital = initial_capital
            portfolio.cash = initial_capital

    def list_trades(self, portfolio_id: int | None = None) -> list[Trade]:
        with self.sessions() as session:
            query = select(Trade).order_by(Trade.exit_time.desc())
            if portfolio_id is not None:
                query = query.where(Trade.portfolio_id == portfolio_id)
            return list(session.scalars(query))

    def list_orders(self, portfolio_id: int | None = None, limit: int = 100) -> list[VirtualOrder]:
        with self.sessions() as session:
            query = select(VirtualOrder).order_by(VirtualOrder.executed_at.desc()).limit(limit)
            if portfolio_id is not None:
                query = query.where(VirtualOrder.portfolio_id == portfolio_id)
            return list(session.scalars(query))

    def record_signal(self, result: SignalResult) -> SignalRecord:
        with self.sessions.begin() as session:
            record = SignalRecord(
                symbol=result.symbol,
                strategy=result.strategy,
                action=result.action.value,
                score=result.score,
                confidence=result.confidence,
                price=result.price,
                provider=result.provider,
                positive_factors="\n".join(result.positive_factors),
                negative_factors="\n".join(result.negative_factors),
                data_problem=result.data_problem,
                analyzed_at=result.analyzed_at,
            )
            session.add(record)
            session.flush()
            return record

    def list_signals(self, limit: int = 100) -> list[SignalRecord]:
        with self.sessions() as session:
            return list(session.scalars(select(SignalRecord).order_by(SignalRecord.analyzed_at.desc()).limit(limit)))

    def start_agent_run(self, run_key: str, symbols: list[str], provider: str) -> AgentRun:
        with self.sessions.begin() as session:
            if session.scalar(select(AgentRun).where(AgentRun.run_key == run_key)):
                raise DuplicateOrderError("Dieser Agentenlauf wurde bereits gestartet.")
            run = AgentRun(
                run_key=run_key,
                status="RUNNING",
                symbols=",".join(symbols),
                providers=provider,
            )
            session.add(run)
            session.flush()
            return run

    def finish_agent_run(self, run_id: int, signals: int, actions: int, errors: list[str]) -> None:
        with self.sessions.begin() as session:
            run = session.get(AgentRun, run_id)
            if run:
                finished = datetime.now(UTC)
                started = run.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                run.status = "FAILED" if errors else "SUCCESS"
                run.finished_at = finished
                run.duration_seconds = (finished - started).total_seconds()
                run.generated_signals = signals
                run.virtual_actions = actions
                run.error_details = "\n".join(errors)

    def last_agent_run(self) -> AgentRun | None:
        with self.sessions() as session:
            return session.scalar(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(1))

    def trading_guard(self, portfolio_id: int) -> tuple[bool, str]:
        """Prüft Tagesverlust und Verlustserie als unveränderliche Schutzschicht."""

        with self.sessions() as session:
            portfolio = session.get(VirtualPortfolio, portfolio_id)
            if portfolio is None:
                return False, "Virtuelles Depot nicht gefunden."
            today = datetime.now(UTC).date()
            trades = list(session.scalars(select(Trade).where(Trade.portfolio_id == portfolio_id).order_by(Trade.exit_time.desc())))
            daily_loss = sum(-trade.pnl_eur for trade in trades if trade.exit_time.date() == today and trade.pnl_eur < 0)
            if daily_loss >= portfolio.initial_capital * self.settings.daily_loss_limit_pct:
                return False, "Tägliches Verlustlimit erreicht."
            consecutive_losses = 0
            for trade in trades:
                if trade.pnl_eur < 0:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= self.settings.max_consecutive_losses:
                return False, "Pause nach drei aufeinanderfolgenden Verlusttrades."
            return True, "Schutzregeln erfüllt."
