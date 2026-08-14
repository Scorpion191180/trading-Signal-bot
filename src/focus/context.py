"""Kostenloser Zusatzkontext für D-Wave aus Märkten und aktuellen Nachrichten."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.news import NewsItem, NewsProvider, NewsProviderError, YFinanceNewsProvider, news_score

from .analysis import ExternalMarketContext

MARKET_SYMBOLS = (
    "QBTS",
    "IONQ",
    "RGTI",
    "QUBT",
    "^IXIC",
    "^GSPC",
    "SOXX",
    "^VIX",
    "GC=F",
    "EURUSD=X",
)
NEWS_SYMBOLS = ("QBTS", "IONQ", "RGTI", "QUBT", "^IXIC", "^GSPC")


def _default_market_loader() -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            list(MARKET_SYMBOLS),
            period="5d",
            interval="5m",
            auto_adjust=False,
            prepost=True,
            progress=False,
            threads=False,
            timeout=15,
        )


def _close_frame(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            closes = data["Close"]
        elif "Close" in data.columns.get_level_values(1):
            closes = data.xs("Close", axis=1, level=1)
        else:
            return pd.DataFrame()
        return closes.to_frame() if isinstance(closes, pd.Series) else closes
    if any(symbol in data.columns for symbol in MARKET_SYMBOLS):
        return data
    if "Close" in data.columns:
        return data[["Close"]].rename(columns={"Close": "QBTS"})
    return pd.DataFrame()


def _short_return(closes: pd.DataFrame, symbol: str) -> float | None:
    if symbol not in closes:
        return None
    series = pd.to_numeric(closes[symbol], errors="coerce").dropna()
    if len(series) < 2:
        return None
    reference_index = max(len(series) - 7, 0)
    reference = float(series.iloc[reference_index])
    return (float(series.iloc[-1]) / reference - 1) * 100 if reference > 0 else None


def score_market_prices(data: pd.DataFrame) -> tuple[float, tuple[str, ...], bool]:
    """Verdichtet etwa 30 Minuten Marktreaktion; keine Quelle kann allein dominieren."""

    closes = _close_frame(data)
    returns = {symbol: _short_return(closes, symbol) for symbol in MARKET_SYMBOLS}
    components: list[tuple[float, float]] = []
    reasons: list[str] = []

    def add(symbol: str, label: str, weight: float, sensitivity: float) -> None:
        value = returns[symbol]
        if value is None or not np.isfinite(value):
            return
        component = float(np.clip(50 + value * sensitivity, 15, 85))
        components.append((component, weight))
        reasons.append(f"{label} {value:+.2f} %/30 Min")

    add("QBTS", "D-Wave USA", 0.30, 8.0)
    peer_values = [returns[symbol] for symbol in ("IONQ", "RGTI", "QUBT")]
    finite_peers = [value for value in peer_values if value is not None and np.isfinite(value)]
    if finite_peers:
        peer_return = float(np.median(finite_peers))
        components.append((float(np.clip(50 + peer_return * 7.0, 15, 85)), 0.18))
        reasons.append(f"Quantum-Vergleich {peer_return:+.2f} %/30 Min")
    add("^IXIC", "Nasdaq", 0.16, 10.0)
    add("^GSPC", "S&P 500", 0.08, 10.0)
    add("SOXX", "Halbleiter", 0.10, 8.0)
    add("^VIX", "VIX (invers)", 0.10, -5.0)
    add("EURUSD=X", "EUR/USD (invers)", 0.05, -4.0)
    add("GC=F", "Gold", 0.03, -2.0)
    if not components:
        return 50.0, (), False
    total_weight = sum(weight for _score, weight in components)
    score = sum(component * weight for component, weight in components) / total_weight
    return round(float(np.clip(score, 15, 85)), 1), tuple(reasons[:6]), True


class FocusContextProvider:
    """Lädt reale Zusatzdaten; Ausfälle bleiben neutral und blockieren den Kursbot nicht."""

    def __init__(
        self,
        *,
        news_provider: NewsProvider | None = None,
        market_loader: Callable[[], pd.DataFrame] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.news_provider = news_provider or YFinanceNewsProvider(count_per_symbol=4)
        self.market_loader = market_loader or _default_market_loader
        self.clock = clock or (lambda: datetime.now(UTC))

    def snapshot(self) -> tuple[ExternalMarketContext, tuple[NewsItem, ...]]:
        current = self.clock()
        reasons: list[str] = []
        errors: list[str] = []
        market_score = 50.0
        market_available = False
        try:
            market_score, market_reasons, market_available = score_market_prices(
                self.market_loader()
            )
            reasons.extend(market_reasons)
        except Exception as exc:  # yfinance bündelt mehrere Netzwerkfehler
            errors.append(f"Marktdaten: {exc}")

        items: tuple[NewsItem, ...] = ()
        news_factor = 0.5
        try:
            items = tuple(self.news_provider.get_news(list(NEWS_SYMBOLS)))
            news_factor = news_score(items, now=current)
            reasons.append(f"Nachrichtenfaktor {news_factor:.2f} aus {len(items)} Meldungen")
        except NewsProviderError as exc:
            errors.append(f"Nachrichten: {exc}")

        news_available = bool(items)
        if market_available and news_available:
            combined = market_score * 0.75 + news_factor * 100 * 0.25
        elif market_available:
            combined = market_score
        elif news_available:
            combined = 50 + (news_factor - 0.5) * 20
        else:
            combined = 50.0
        if errors and not reasons:
            reasons.append("Zusatzquellen ausgefallen · neutral behandelt")
        headlines = tuple(item.title for item in items[:3])
        return (
            ExternalMarketContext(
                score=round(float(np.clip(combined, 15, 85)), 1),
                market_score=market_score,
                news_score=news_factor,
                reasons=tuple(reasons[:7]),
                headlines=headlines,
                updated_at=current,
                available=market_available or news_available,
            ),
            items,
        )
