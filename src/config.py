"""Zentrale, reproduzierbare Anwendungskonfiguration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ScoringWeights:
    """Versionierte Gewichte des transparenten 100-Punkte-Modells."""

    version: str = "v1"
    higher_trend: int = 15
    intraday_trend: int = 15
    momentum: int = 10
    volume: int = 15
    levels: int = 10
    patterns: int = 10
    news: int = 15
    market: int = 10

    def as_dict(self) -> dict[str, int]:
        return {
            "Übergeordneter Trend": self.higher_trend,
            "Intraday-Trend": self.intraday_trend,
            "Momentum": self.momentum,
            "Volumen": self.volume,
            "Unterstützung/Widerstand": self.levels,
            "Muster": self.patterns,
            "Nachrichten": self.news,
            "Markt/Branche": self.market,
        }

    def __post_init__(self) -> None:
        if sum(self.as_dict().values()) != 100:
            raise ValueError("Die Signalgewichte müssen zusammen 100 ergeben.")


@dataclass(frozen=True)
class StrategyProfile:
    """Unveränderliche Schutz- und Signalschwellen eines Strategiemodus."""

    name: str
    version: str
    buy_threshold: int
    sell_threshold: int
    max_position_pct: float
    risk_per_trade_pct: float
    max_open_positions: int
    stop_atr: float
    target_atr: float
    min_relative_volume: float
    max_spread_pct: float
    minimum_reward_risk: float


STRATEGIES: dict[str, StrategyProfile] = {
    "Defensiv": StrategyProfile(
        "Defensiv", "v1", 75, 35, 0.10, 0.003, 3, 2.2, 4.4, 1.0, 0.003, 2.0
    ),
    "Normal": StrategyProfile(
        "Normal", "v1", 65, 40, 0.15, 0.005, 5, 1.8, 3.2, 0.8, 0.005, 1.7
    ),
    "Aggressiv": StrategyProfile(
        "Aggressiv", "v1", 58, 42, 0.20, 0.008, 7, 1.4, 2.4, 0.6, 0.008, 1.5
    ),
}


@dataclass(frozen=True)
class AppSettings:
    """Laufzeitkonfiguration; Secrets werden ausschließlich aus der Umgebung gelesen."""

    database_url: str = "sqlite:///data/trading_signal_live.db"
    data_provider: str = "auto"
    twelve_data_api_key: str = ""
    alpaca_api_key_id: str = ""
    alpaca_api_secret_key: str = ""
    timezone: str = "Europe/Berlin"
    default_interval: str = "5m"
    default_period: str = "5d"
    stale_after_minutes: int = 20
    analysis_interval_minutes: int = 30
    starting_capital: float = 10_000.0
    order_fee: float = 1.0
    spread_pct: float = 0.001
    slippage_pct: float = 0.0005
    daily_loss_limit_pct: float = 0.02
    max_consecutive_losses: int = 3
    default_symbols: tuple[str, ...] = field(
        default=("QBTS", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN", "META", "GOOGL")
    )

    @classmethod
    def from_env(cls) -> AppSettings:
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/trading_signal_live.db"),
            data_provider=os.getenv("DATA_PROVIDER", "auto").lower(),
            twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY", ""),
            alpaca_api_key_id=os.getenv("APCA_API_KEY_ID", ""),
            alpaca_api_secret_key=os.getenv("APCA_API_SECRET_KEY", ""),
            timezone=os.getenv("APP_TIMEZONE", "Europe/Berlin"),
            stale_after_minutes=int(os.getenv("STALE_AFTER_MINUTES", "20")),
            starting_capital=float(os.getenv("STARTING_CAPITAL", "10000")),
            order_fee=float(os.getenv("ORDER_FEE", "1")),
            spread_pct=float(os.getenv("SPREAD_PCT", "0.001")),
            slippage_pct=float(os.getenv("SLIPPAGE_PCT", "0.0005")),
        )

    def ensure_local_directories(self) -> None:
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///" )).expanduser().parent.mkdir(
                parents=True, exist_ok=True
            )


WEIGHTS = ScoringWeights()
