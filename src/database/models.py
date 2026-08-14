"""Persistentes Datenmodell für Version 0.1 und vorbereitete Erweiterungen."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(200), default="")
    priority: Mapped[bool] = mapped_column(Boolean, default=False)
    trading_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_only: Mapped[bool] = mapped_column(Boolean, default=True)
    interval: Mapped[str] = mapped_column(String(10), default="5m")
    exchange_timezone: Mapped[str] = mapped_column(String(60), default="America/New_York")
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RealPosition(Base):
    __tablename__ = "real_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    isin_wkn: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    average_price: Mapped[float] = mapped_column(Float)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    reference_market: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VirtualPortfolio(Base):
    __tablename__ = "virtual_portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    strategy: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(30), default="v1")
    initial_capital: Mapped[float] = mapped_column(Float, default=10_000.0)
    cash: Mapped[float] = mapped_column(Float, default=10_000.0)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    positions: Mapped[list[VirtualPosition]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class VirtualPosition(Base):
    __tablename__ = "virtual_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("virtual_portfolios.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    average_price: Mapped[float] = mapped_column(Float)
    entry_fees_remaining: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    entry_reason: Mapped[str] = mapped_column(Text)
    entry_score: Mapped[float] = mapped_column(Float)
    weight_version: Mapped[str] = mapped_column(String(30), default="v1")
    entry_provider: Mapped[str] = mapped_column(String(80), default="unbekannt")
    last_provider: Mapped[str] = mapped_column(String(80), default="unbekannt")
    entry_news_factor: Mapped[float] = mapped_column(Float, default=0.5)
    entry_news_ids: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    portfolio: Mapped[VirtualPortfolio] = relationship(back_populates="positions")


class VirtualOrder(Base):
    __tablename__ = "virtual_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("virtual_portfolios.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    market_price: Mapped[float] = mapped_column(Float)
    execution_price: Mapped[float] = mapped_column(Float)
    gross_value: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float)
    spread_cost: Mapped[float] = mapped_column(Float)
    slippage_cost: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    signal_score: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(80), default="unbekannt")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("virtual_portfolios.id", ondelete="CASCADE"), index=True)
    strategy: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(30))
    weight_version: Mapped[str] = mapped_column(String(30))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    quantity: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    pnl_eur: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float)
    entry_reason: Mapped[str] = mapped_column(Text)
    exit_reason: Mapped[str] = mapped_column(Text)
    entry_score: Mapped[float] = mapped_column(Float)
    exit_score: Mapped[float] = mapped_column(Float)
    entry_provider: Mapped[str] = mapped_column(String(80), default="unbekannt")
    exit_provider: Mapped[str] = mapped_column(String(80), default="unbekannt")
    entry_news_factor: Mapped[float] = mapped_column(Float, default=0.5)
    exit_news_factor: Mapped[float] = mapped_column(Float, default=0.5)
    entry_news_ids: Mapped[str] = mapped_column(Text, default="")
    exit_news_ids: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    max_favorable: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse: Mapped[float | None] = mapped_column(Float, nullable=True)


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    strategy: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(80))
    news_factor: Mapped[float] = mapped_column(Float, default=0.5)
    news_ids: Mapped[str] = mapped_column(Text, default="")
    positive_factors: Mapped[str] = mapped_column(Text, default="")
    negative_factors: Mapped[str] = mapped_column(Text, default="")
    data_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class FocusForecast(Base):
    """Unveränderliche D-Wave-Prognose, bevor der spätere Kurs bekannt ist."""

    __tablename__ = "focus_forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(30), default="focus-market-v1", index=True)
    forecast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(24))
    model_score: Mapped[float] = mapped_column(Float)
    forecast_low: Mapped[float] = mapped_column(Float)
    forecast_high: Mapped[float] = mapped_column(Float)
    market_regime: Mapped[str] = mapped_column(String(40))
    strategy_votes: Mapped[str] = mapped_column(Text, default="")
    spread_percent: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FocusForecastOutcome(Base):
    """Nur mit einem später beobachteten Kurs erzeugtes Walk-forward-Ergebnis."""

    __tablename__ = "focus_forecast_outcomes"
    __table_args__ = (UniqueConstraint("forecast_id", "horizon_minutes", name="uq_focus_forecast_horizon"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_id: Mapped[int] = mapped_column(
        ForeignKey("focus_forecasts.id", ondelete="CASCADE"), index=True
    )
    horizon_minutes: Mapped[int] = mapped_column(Integer, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_price: Mapped[float] = mapped_column(Float)
    return_percent: Mapped[float] = mapped_column(Float)
    direction_hit: Mapped[bool] = mapped_column(Boolean)
    zone_hit: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FocusBotStatus(Base):
    """Heartbeat und letzter sicherer Zustand des unabhängigen Papier-Bots."""

    __tablename__ = "focus_bot_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    run_state: Mapped[str] = mapped_column(String(20), default="STARTING", index=True)
    signal_action: Mapped[str] = mapped_column(String(20), default="WAIT")
    signal_score: Mapped[float] = mapped_column(Float, default=50.0)
    account_state: Mapped[str] = mapped_column(String(30), default="CASH")
    message: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_quote_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_strategy_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(30))
    configuration_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WeightVersion(Base):
    __tablename__ = "weight_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(30), unique=True)
    configuration_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    symbols: Mapped[str] = mapped_column(Text, default="")
    providers: Mapped[str] = mapped_column(Text, default="")
    generated_signals: Mapped[int] = mapped_column(Integer, default=0)
    virtual_actions: Mapped[int] = mapped_column(Integer, default=0)
    error_details: Mapped[str] = mapped_column(Text, default="")


class NewsRecord(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(160), unique=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    sentiment: Mapped[str] = mapped_column(String(20))
    impact: Mapped[float] = mapped_column(Float)
    credibility: Mapped[float] = mapped_column(Float, default=0.5)
    direct_relevance: Mapped[bool] = mapped_column(Boolean, default=True)
    possibly_priced_in: Mapped[bool] = mapped_column(Boolean, default=False)
    related_symbols: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotificationRecord(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    deduplication_key: Mapped[str] = mapped_column(String(160), unique=True)
    channel: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SystemError(Base):
    __tablename__ = "system_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    component: Mapped[str] = mapped_column(String(80))
    public_message: Mapped[str] = mapped_column(Text)
    technical_details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
