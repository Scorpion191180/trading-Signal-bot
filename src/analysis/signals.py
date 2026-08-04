"""Transparentes, regelbasiertes Signalmodell für experimentelle Einschätzungen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite

import pandas as pd

from src.config import WEIGHTS, ScoringWeights, StrategyProfile

from .indicators import add_indicators
from .levels import PriceZone, nearest_levels
from .patterns import candlestick_context


class SignalAction(StrEnum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SignalResult:
    symbol: str
    action: SignalAction
    score: float
    confidence: float
    price: float
    analyzed_at: datetime
    data_timestamp: datetime
    provider: str
    strategy: str
    weight_version: str
    positive_factors: tuple[str, ...]
    negative_factors: tuple[str, ...]
    components: dict[str, float]
    entry_zone: tuple[float, float] | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    reward_risk: float | None
    trend: str
    data_problem: str | None
    zones: tuple[PriceZone, ...]
    experimental: bool = True


def _bounded(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(max(float(value), lower), upper)


def _blocked(
    symbol: str,
    profile: StrategyProfile,
    provider: str,
    message: str,
    frame: pd.DataFrame | None,
    weights: ScoringWeights,
) -> SignalResult:
    timestamp = datetime.now(UTC)
    if frame is not None and not frame.empty:
        timestamp = pd.Timestamp(frame.index[-1]).to_pydatetime()
    return SignalResult(
        symbol=symbol,
        action=SignalAction.BLOCKED,
        score=0.0,
        confidence=0.0,
        price=float(frame["close"].iloc[-1]) if frame is not None and not frame.empty and "close" in frame else 0.0,
        analyzed_at=datetime.now(UTC),
        data_timestamp=timestamp,
        provider=provider,
        strategy=profile.name,
        weight_version=weights.version,
        positive_factors=(),
        negative_factors=(message,),
        components={},
        entry_zone=None,
        stop_loss=None,
        target_1=None,
        target_2=None,
        reward_risk=None,
        trend="Unklar",
        data_problem=message,
        zones=(),
    )


def analyze_signal(
    symbol: str,
    frame: pd.DataFrame,
    profile: StrategyProfile,
    *,
    provider: str,
    stale_after_minutes: int = 20,
    enforce_freshness: bool = True,
    weights: ScoringWeights = WEIGHTS,
    news_factor: float = 0.5,
    market_factor: float = 0.5,
) -> SignalResult:
    """Erzeugt ein erklärbares Signal; unzureichende Daten blockieren den Handel."""

    if frame is None or frame.empty or len(frame) < 200:
        return _blocked(symbol, profile, provider, "Mindestens 200 abgeschlossene Kerzen erforderlich.", frame, weights)
    data = add_indicators(frame)
    latest = data.iloc[-1]
    data_timestamp = pd.Timestamp(data.index[-1]).to_pydatetime()
    age_minutes = (datetime.now(UTC) - data_timestamp).total_seconds() / 60
    if enforce_freshness and age_minutes > stale_after_minutes:
        return _blocked(
            symbol,
            profile,
            provider,
            f"Kursdaten sind {age_minutes:.0f} Minuten alt und damit veraltet.",
            data,
            weights,
        )
    required = ["ema_20", "ema_50", "rsi_14", "macd_hist", "atr_14", "relative_volume"]
    if any(pd.isna(latest[column]) for column in required):
        return _blocked(symbol, profile, provider, "Technische Kennzahlen sind noch unvollständig.", data, weights)
    if float(latest["volume"]) <= 0:
        return _blocked(symbol, profile, provider, "Kein belastbares Volumen für die letzte Kerze.", data, weights)

    price = float(latest["close"])
    ema20 = float(latest["ema_20"])
    ema50 = float(latest["ema_50"])
    ema200 = float(latest["ema_200"])
    current_rsi = float(latest["rsi_14"])
    relative_volume = float(latest["relative_volume"])
    pattern_factor, pattern_positive, pattern_negative = candlestick_context(data)
    support, resistance, zones = nearest_levels(data)

    higher_factor = sum((price > ema200, ema50 > ema200, price > ema50)) / 3
    intraday_factor = sum((price > ema20, ema20 > ema50, price > float(latest["vwap"]))) / 3
    rsi_factor = 1 - abs(current_rsi - 58) / 58
    macd_factor = 0.7 if float(latest["macd_hist"]) > 0 else 0.3
    momentum_factor = _bounded((rsi_factor + macd_factor) / 2)
    volume_factor = _bounded(relative_volume / 1.5)
    if support and resistance:
        downside = max(price - support, 1e-9)
        upside = max(resistance - price, 0.0)
        level_factor = _bounded(upside / (upside + downside))
    elif support:
        level_factor = 0.65
    elif resistance:
        level_factor = 0.35
    else:
        level_factor = 0.5
    raw_components = {
        "Übergeordneter Trend": higher_factor,
        "Intraday-Trend": intraday_factor,
        "Momentum": momentum_factor,
        "Volumen": volume_factor,
        "Unterstützung/Widerstand": level_factor,
        "Muster": pattern_factor,
        "Nachrichten": _bounded(news_factor),
        "Markt/Branche": _bounded(market_factor),
    }
    components = {
        name: round(raw_components[name] * maximum, 2)
        for name, maximum in weights.as_dict().items()
    }
    score = round(sum(components.values()), 2)
    positive: list[str] = []
    negative: list[str] = []
    if price > ema20 > ema50:
        positive.append("Kurs und EMA 20 liegen über EMA 50")
    else:
        negative.append("Kurzfristige EMA-Struktur nicht bullisch")
    if price > ema200:
        positive.append("Kurs über EMA 200")
    else:
        negative.append("Kurs nicht über EMA 200")
    if 45 <= current_rsi <= 70:
        positive.append(f"RSI im konstruktiven Bereich ({current_rsi:.1f})")
    elif current_rsi > 70:
        negative.append(f"RSI möglicherweise überkauft ({current_rsi:.1f})")
    else:
        negative.append(f"RSI schwach ({current_rsi:.1f})")
    if float(latest["macd_hist"]) > 0:
        positive.append("MACD-Histogramm positiv")
    else:
        negative.append("MACD-Histogramm negativ")
    if relative_volume >= profile.min_relative_volume:
        positive.append(f"Relatives Volumen {relative_volume:.2f}")
    else:
        negative.append(f"Relatives Volumen zu gering ({relative_volume:.2f})")
    positive.extend(pattern_positive)
    negative.extend(pattern_negative)

    action = SignalAction.HOLD
    if score >= profile.buy_threshold and relative_volume >= profile.min_relative_volume:
        action = SignalAction.BUY
    elif score <= profile.sell_threshold:
        action = SignalAction.SELL
    atr_value = float(latest["atr_14"])
    stop_loss = price - profile.stop_atr * atr_value
    target_1 = price + profile.target_atr * atr_value
    target_2 = price + profile.target_atr * 1.5 * atr_value
    risk = price - stop_loss
    reward_risk = (target_1 - price) / risk if risk > 0 else None
    if reward_risk is not None and reward_risk < profile.minimum_reward_risk:
        negative.append(f"Chance-Risiko-Verhältnis nur {reward_risk:.2f}")
        if action is SignalAction.BUY:
            action = SignalAction.HOLD
    finite_indicators = sum(isfinite(float(latest[column])) for column in required) / len(required)
    confidence = round(_bounded(0.25 + min(len(data) / 1200, 0.25) + finite_indicators * 0.25) * 100, 1)
    trend = "Aufwärts" if higher_factor >= 2 / 3 else "Abwärts" if higher_factor <= 1 / 3 else "Seitwärts/unklar"
    return SignalResult(
        symbol=symbol.upper(),
        action=action,
        score=score,
        confidence=confidence,
        price=price,
        analyzed_at=datetime.now(UTC),
        data_timestamp=data_timestamp,
        provider=provider,
        strategy=profile.name,
        weight_version=weights.version,
        positive_factors=tuple(positive),
        negative_factors=tuple(negative),
        components=components,
        entry_zone=(price - 0.25 * atr_value, price + 0.25 * atr_value),
        stop_loss=round(stop_loss, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        reward_risk=round(reward_risk, 2) if reward_risk is not None else None,
        trend=trend,
        data_problem=None,
        zones=tuple(zones),
    )
