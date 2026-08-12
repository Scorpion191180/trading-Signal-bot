"""Kursabruf und saubere Zeitebenen für das deutsche D-Wave-Instrument."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

from src.data import MarketDataProvider, MarketDataRequest, ProviderError


@dataclass(frozen=True)
class TimeframeBundle:
    frames: dict[str, pd.DataFrame]
    errors: dict[str, str]
    provider: str
    symbol: str
    venue: str


GERMAN_VENUES = (
    ("RQ0.SG", "Stuttgart"),
    ("RQ0.F", "Frankfurt"),
)


def resample_ohlcv(
    frame: pd.DataFrame,
    rule: str,
    *,
    minimum_source_rows: int = 1,
    drop_future_label: bool = False,
) -> pd.DataFrame:
    """Verdichtet nur vollständige Quellkerzen und verwirft laufende Kalenderperioden."""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The 'generic' unit for NumPy timedelta is deprecated.*",
            category=DeprecationWarning,
        )
        grouped = frame.resample(rule, label="right", closed="right")
        result = grouped.agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        counts = grouped["close"].count()
    result = result.loc[counts >= minimum_source_rows].dropna(subset=["open", "high", "low", "close"])
    if drop_future_label and not result.empty:
        result = result.loc[result.index <= frame.index[-1]]
    result.attrs.update(frame.attrs)
    return result


def load_dwave_timeframes(provider: MarketDataProvider) -> TimeframeBundle:
    """Wählt den frischeren deutschen Platz ohne Wechsel auf den US-Handelsplatz."""

    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    candidate_errors: dict[str, str] = {}
    venue_candidates: list[tuple[pd.Timestamp, float, str, str, pd.DataFrame]] = []
    for symbol, venue in GERMAN_VENUES:
        try:
            minute_frame = provider.history(
                MarketDataRequest(symbol, "1m", "7d", minimum_rows=60, require_latest_volume=False)
            )
            recent_volume = float(minute_frame["volume"].tail(60).sum())
            venue_candidates.append((minute_frame.index[-1], recent_volume, symbol, venue, minute_frame))
        except ProviderError as exc:
            candidate_errors[f"1m-{symbol}"] = str(exc)
    if not venue_candidates:
        return TimeframeBundle(
            frames={},
            errors=candidate_errors,
            provider=provider.name,
            symbol="RQ0",
            venue="kein deutscher Platz verfügbar",
        )
    _, _, selected_symbol, selected_venue, minute_frame = max(
        venue_candidates,
        key=lambda value: (value[0], value[1]),
    )
    frames["1m"] = minute_frame
    requests = {
        "5m": MarketDataRequest(selected_symbol, "5m", "1mo", minimum_rows=80, require_latest_volume=False),
        "1h": MarketDataRequest(selected_symbol, "1h", "6mo", minimum_rows=80, require_latest_volume=False),
        "1d": MarketDataRequest(selected_symbol, "1d", "5y", minimum_rows=200, require_latest_volume=False),
    }
    for key, request in requests.items():
        try:
            frames[key] = provider.history(request)
        except ProviderError as exc:
            errors[key] = str(exc)

    five_minutes = frames.get("5m")
    if five_minutes is not None and not five_minutes.empty:
        frames["15m"] = resample_ohlcv(
            five_minutes,
            "15min",
            minimum_source_rows=1,
            drop_future_label=True,
        )
    daily = frames.get("1d")
    if daily is not None and not daily.empty:
        frames["1wk"] = resample_ohlcv(daily, "W-FRI", drop_future_label=True)
        frames["1mo"] = resample_ohlcv(daily, "ME", drop_future_label=True)
    return TimeframeBundle(
        frames=frames,
        errors=errors,
        provider=provider.name,
        symbol=selected_symbol,
        venue=selected_venue,
    )
