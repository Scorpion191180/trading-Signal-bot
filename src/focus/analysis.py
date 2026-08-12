"""Erklärbare Multi-Timeframe-Logik für sehr kurze D-Wave-Trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.analysis.indicators import atr, ema, rsi


@dataclass(frozen=True)
class Instrument:
    name: str
    yahoo_symbol: str
    exchange_symbol: str
    isin: str
    wkn: str
    venue: str
    currency: str


DWAVE_INSTRUMENT = Instrument(
    name="D-Wave Quantum Inc.",
    yahoo_symbol="RQ0.F",
    exchange_symbol="RQ0",
    isin="US26740W1099",
    wkn="A3DSV9",
    venue="Deutscher Markt",
    currency="EUR",
)


@dataclass(frozen=True)
class TimeframeSpec:
    key: str
    label: str
    fast_ema: int
    slow_ema: int
    chart_rows: int


TIMEFRAME_SPECS = (
    TimeframeSpec("1m", "1 Minute", 8, 21, 180),
    TimeframeSpec("5m", "5 Minuten", 8, 21, 180),
    TimeframeSpec("15m", "15 Minuten", 8, 21, 160),
    TimeframeSpec("1h", "1 Stunde", 10, 30, 160),
    TimeframeSpec("1d", "Tageschart", 20, 50, 220),
    TimeframeSpec("1wk", "Wochenchart", 10, 30, 180),
    TimeframeSpec("1mo", "Monatschart", 6, 18, 100),
)
SPEC_BY_KEY = {spec.key: spec for spec in TIMEFRAME_SPECS}


@dataclass(frozen=True)
class TimeframeAnalysis:
    key: str
    label: str
    score: float
    trend: str
    setup: str
    price: float
    rsi: float
    relative_volume: float | None
    data_timestamp: datetime
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FocusPosition:
    invested: bool = False
    average_price: float | None = None
    quantity: float | None = None


@dataclass(frozen=True)
class IntradaySignal:
    action: str
    headline: str
    score: float
    strength: str
    color: str
    current_price: float
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    target: float | None
    holding_period: str
    reasons: tuple[str, ...]
    warning: str
    data_age_minutes: float
    market_open: bool


def add_focus_indicators(frame: pd.DataFrame, spec: TimeframeSpec) -> pd.DataFrame:
    data = frame.copy()
    data["ema_fast"] = ema(data["close"], spec.fast_ema)
    data["ema_slow"] = ema(data["close"], spec.slow_ema)
    data["ema_200"] = ema(data["close"], 200) if len(data) >= 200 else np.nan
    data["rsi_14"] = rsi(data["close"], 14)
    data["macd"] = ema(data["close"], 12) - ema(data["close"], 26)
    data["macd_signal"] = ema(data["macd"], 9)
    data["macd_hist"] = data["macd"] - data["macd_signal"]
    data["atr_14"] = atr(data, 14)
    data["previous_high_20"] = data["high"].shift(1).rolling(20, min_periods=10).max()
    data["previous_low_20"] = data["low"].shift(1).rolling(20, min_periods=10).min()
    average_volume = data["volume"].shift(1).rolling(20, min_periods=5).mean()
    data["relative_volume"] = data["volume"] / average_volume.replace(0.0, np.nan)
    return data


def _momentum_factor(current_rsi: float, macd_hist: float, previous_hist: float) -> float:
    if 52 <= current_rsi <= 68:
        rsi_factor = 1.0
    elif 45 <= current_rsi < 52 or 68 < current_rsi <= 73:
        rsi_factor = 0.55
    elif current_rsi > 78 or current_rsi < 35:
        rsi_factor = 0.05
    else:
        rsi_factor = 0.3
    macd_factor = 1.0 if macd_hist > 0 and macd_hist >= previous_hist else 0.6 if macd_hist > 0 else 0.15
    return (rsi_factor * 0.55) + (macd_factor * 0.45)


def analyze_timeframe(frame: pd.DataFrame, spec: TimeframeSpec) -> tuple[TimeframeAnalysis, pd.DataFrame]:
    if len(frame) < max(spec.slow_ema + 10, 35):
        raise ValueError(f"{spec.label}: zu wenige abgeschlossene Kerzen ({len(frame)}).")
    data = add_focus_indicators(frame, spec)
    latest = data.iloc[-1]
    previous = data.iloc[-2]
    close = float(latest["close"])
    fast = float(latest["ema_fast"])
    slow = float(latest["ema_slow"])
    current_rsi = float(latest["rsi_14"])
    macd_hist = float(latest["macd_hist"])
    previous_hist = float(previous["macd_hist"])
    long_reference = latest["ema_200"]
    if pd.isna(long_reference):
        lookback = min(20, len(data) - 1)
        long_condition = close > float(data["close"].iloc[-1 - lookback])
    else:
        long_condition = close > float(long_reference)

    trend_checks = (
        close > fast,
        fast > slow,
        fast > float(data["ema_fast"].iloc[-4]),
        long_condition,
    )
    trend_factor = sum(trend_checks) / len(trend_checks)
    momentum_factor = _momentum_factor(current_rsi, macd_hist, previous_hist)
    previous_high = float(latest["previous_high_20"])
    previous_low = float(latest["previous_low_20"])
    bullish_candle = close > float(latest["open"])
    breakout = close > previous_high
    pullback = close > fast and float(latest["low"]) <= fast * 1.006 and bullish_candle
    if breakout:
        structure_factor, setup = 1.0, "Ausbruch"
    elif pullback:
        structure_factor, setup = 0.8, "Trend-Rücksetzer"
    elif close > (previous_high + previous_low) / 2:
        structure_factor, setup = 0.55, "obere Handelsspanne"
    else:
        structure_factor, setup = 0.2, "schwache Struktur"
    relative_volume_value = latest["relative_volume"]
    if pd.isna(relative_volume_value) or float(relative_volume_value) <= 0:
        volume_factor = 0.5
        relative_volume = None
    else:
        relative_volume = float(relative_volume_value)
        volume_factor = 1.0 if relative_volume >= 1.4 else 0.7 if relative_volume >= 0.9 else 0.3

    score = round(
        (trend_factor * 45) + (momentum_factor * 25) + (structure_factor * 20) + (volume_factor * 10),
        1,
    )
    trend = "Aufwärts" if score >= 62 else "Abwärts" if score <= 40 else "Seitwärts"
    reasons: list[str] = []
    warnings: list[str] = []
    reasons.append("Kurs über schneller und langsamer EMA" if close > fast > slow else "EMA-Trend noch nicht vollständig positiv")
    reasons.append(f"RSI {current_rsi:.0f} · Momentum {'positiv' if macd_hist > 0 else 'negativ'}")
    reasons.append(f"Chartstruktur: {setup}")
    if relative_volume is None:
        warnings.append("Volumenbestätigung für die jüngste Kerze fehlt")
    elif relative_volume < 0.7:
        warnings.append(f"geringes relatives Volumen ({relative_volume:.2f})")
    if current_rsi > 73:
        warnings.append("kurzfristig überkauft – Einstieg nicht hinterherlaufen")
    timestamp = pd.Timestamp(data.index[-1]).to_pydatetime()
    return (
        TimeframeAnalysis(
            key=spec.key,
            label=spec.label,
            score=score,
            trend=trend,
            setup=setup,
            price=close,
            rsi=current_rsi,
            relative_volume=relative_volume,
            data_timestamp=timestamp,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        ),
        data,
    )


def analyze_timeframes(
    frames: dict[str, pd.DataFrame],
) -> tuple[dict[str, TimeframeAnalysis], dict[str, pd.DataFrame], dict[str, str]]:
    analyses: dict[str, TimeframeAnalysis] = {}
    enriched: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for spec in TIMEFRAME_SPECS:
        frame = frames.get(spec.key)
        if frame is None or frame.empty:
            errors[spec.key] = f"{spec.label}: keine Daten verfügbar."
            continue
        try:
            analyses[spec.key], enriched[spec.key] = analyze_timeframe(frame, spec)
        except (ValueError, IndexError) as exc:
            errors[spec.key] = str(exc)
    return analyses, enriched, errors


def _is_german_market_open(now: datetime) -> bool:
    berlin = now.astimezone(ZoneInfo("Europe/Berlin"))
    return berlin.weekday() < 5 and time(7, 30) <= berlin.time().replace(tzinfo=None) <= time(22, 0)


def _signal_strength(score: float) -> str:
    return "stark" if score >= 72 or score <= 28 else "moderat" if score >= 62 or score <= 40 else "schwach"


def build_intraday_signal(
    analyses: dict[str, TimeframeAnalysis],
    enriched: dict[str, pd.DataFrame],
    position: FocusPosition,
    *,
    now: datetime | None = None,
    enforce_market_hours: bool = True,
    maximum_data_age_minutes: float = 4.0,
    live_price: float | None = None,
) -> IntradaySignal:
    current_time = now or datetime.now(UTC)
    required = ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo")
    missing = [key for key in required if key not in analyses]
    fallback_price = next((value.price for value in analyses.values()), 0.0)
    if missing:
        return IntradaySignal(
            action="NO_SIGNAL",
            headline="KEIN SIGNAL – Daten unvollständig",
            score=50.0,
            strength="keine",
            color="#64748b",
            current_price=fallback_price,
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            target=None,
            holding_period="5–30 Minuten",
            reasons=("Für einen Kurzfrist-Trade müssen alle sieben Zeitebenen verfügbar sein.",),
            warning="Fehlend: " + ", ".join(SPEC_BY_KEY[key].label for key in missing),
            data_age_minutes=float("inf"),
            market_open=False,
        )

    minute = analyses["1m"]
    candle_end = minute.data_timestamp.astimezone(UTC) + timedelta(minutes=1)
    age_minutes = max((current_time.astimezone(UTC) - candle_end).total_seconds() / 60, 0.0)
    market_open = _is_german_market_open(current_time)
    price = live_price if live_price is not None and live_price > 0 else minute.price
    minute_data = enriched["1m"]
    latest = minute_data.iloc[-1]
    one_minute_atr = float(latest["atr_14"])
    if not np.isfinite(one_minute_atr) or one_minute_atr <= 0:
        one_minute_atr = price * 0.006
    entry_low = price - (0.10 * one_minute_atr)
    entry_high = price + (0.15 * one_minute_atr)
    stop_loss = price - one_minute_atr
    target = price + (1.5 * one_minute_atr)

    weights = {"1m": 0.25, "5m": 0.35, "15m": 0.20, "1h": 0.10, "1d": 0.10}
    score = sum(analyses[key].score * weight for key, weight in weights.items())
    if analyses["1wk"].score >= 58 and analyses["1mo"].score >= 52:
        score += 2
    elif analyses["1wk"].score <= 38 and analyses["1mo"].score <= 38:
        score -= 5
    score = round(min(max(score, 0.0), 100.0), 1)

    if enforce_market_hours and not market_open:
        return IntradaySignal(
            "NO_SIGNAL",
            "KEIN SIGNAL – deutscher Markt geschlossen",
            score,
            _signal_strength(score),
            "#64748b",
            price,
            None,
            None,
            None,
            None,
            "5–30 Minuten",
            ("Kurzfristige Signale werden nur während der deutschen Handelszeit freigegeben.",),
            "Der nächste Kurs kann mit einer Lücke eröffnen; jetzt keine Handlung ableiten.",
            age_minutes,
            False,
        )
    if age_minutes > maximum_data_age_minutes:
        return IntradaySignal(
            "NO_SIGNAL",
            "KEIN SIGNAL – Kurs ist zu stark verzögert",
            score,
            _signal_strength(score),
            "#64748b",
            price,
            None,
            None,
            None,
            None,
            "5–30 Minuten",
            (f"Die letzte abgeschlossene 1-Minuten-Kerze ist {age_minutes:.1f} Minuten alt.",),
            "Für einen 5–30-Minuten-Trade sind verzögerte Gratisdaten nicht sicher genug.",
            age_minutes,
            market_open,
        )

    short_volume = max(
        value
        for value in (
            analyses["1m"].relative_volume or 0.0,
            analyses["5m"].relative_volume or 0.0,
        )
    ) >= 0.8
    short_trigger = (
        analyses["1m"].score >= 62
        and analyses["5m"].score >= 62
        and analyses["15m"].score >= 52
        and analyses["1m"].rsi <= 73
        and analyses["1m"].setup in {"Ausbruch", "Trend-Rücksetzer"}
        and short_volume
    )
    context_veto = analyses["1h"].score < 38 or analyses["1d"].score < 35
    bearish_exit = analyses["1m"].score <= 38 and analyses["5m"].score <= 42
    reasons = (
        f"1 Minute {analyses['1m'].score:.0f} · 5 Minuten {analyses['5m'].score:.0f} · "
        f"15 Minuten {analyses['15m'].score:.0f}",
        f"Auslöser: {analyses['1m'].setup}; Stundenfilter {analyses['1h'].trend.lower()}",
        f"Tages-/Wochenkontext: {analyses['1d'].trend.lower()} / {analyses['1wk'].trend.lower()} · "
        f"Volumen {'bestätigt' if short_volume else 'zu schwach'}",
    )

    action = "WAIT"
    headline = "WARTEN – noch kein sauberer Einstieg"
    color = "#f59e0b"
    warning = "Kein Trade, bis 1- und 5-Minuten-Chart gemeinsam bestätigen."
    if position.invested:
        if bearish_exit or score <= 38:
            action, headline, color = "SELL", "VERKAUFEN – kurzfristiger Trend kippt", "#ef4444"
            warning = "Signal bezieht sich auf den kurzfristigen Trade; Ausführung und Spread selbst prüfen."
        elif short_trigger and not context_veto and score >= 64:
            if position.average_price is not None and price >= position.average_price:
                action, headline, color = "ADD", "NACHKAUFEN – erneute Intraday-Bestätigung", "#22c55e"
                warning = "Nicht verbilligen: Das Nachkaufsignal gilt nur oberhalb deines Einstandskurses."
            else:
                action, headline, color = "HOLD", "HALTEN – kein Nachkauf im Verlust", "#38bdf8"
                warning = "Ein positives Setup reicht nicht zum Verbilligen einer verlustreichen Position."
        else:
            action, headline, color = "HOLD", "HALTEN / BEOBACHTEN", "#38bdf8"
            warning = "Stop beachten; ohne neue 1- und 5-Minuten-Bestätigung nicht aufstocken."
    elif short_trigger and not context_veto and score >= 64:
        action, headline, color = "BUY", "KAUFEN – kurzfristiges technisches Signal", "#22c55e"
        warning = "Nur für etwa 5–30 Minuten; bei Unterschreiten des Stops ist das Setup ungültig."

    return IntradaySignal(
        action=action,
        headline=headline,
        score=score,
        strength=_signal_strength(score),
        color=color,
        current_price=price,
        entry_low=entry_low if action in {"BUY", "ADD"} else None,
        entry_high=entry_high if action in {"BUY", "ADD"} else None,
        stop_loss=stop_loss if action in {"BUY", "ADD", "HOLD"} else None,
        target=target if action in {"BUY", "ADD", "HOLD"} else None,
        holding_period="5–30 Minuten",
        reasons=reasons,
        warning=warning,
        data_age_minutes=age_minutes,
        market_open=market_open,
    )
