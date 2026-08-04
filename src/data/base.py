"""Vertrag für Kursdatenquellen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import pandas as pd


class ProviderError(RuntimeError):
    """Verständlich behandelbarer Fehler einer externen Datenquelle."""


@dataclass(frozen=True)
class MarketDataRequest:
    symbol: str
    interval: str = "5m"
    period: str = "5d"
    prepost: bool = False


class MarketDataProvider(Protocol):
    name: str
    is_demo: bool

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        """Liefert OHLCV-Daten mit UTC DatetimeIndex und Standardspalten."""


def source_name(frame: pd.DataFrame, provider: MarketDataProvider) -> str:
    """Liest die tatsächlich verwendete Quelle einer normalisierten Kursreihe."""

    return str(frame.attrs.get("provider", provider.name))


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
INTERVAL_DURATION = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "60m": timedelta(hours=1),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


def recommended_period(interval: str, *, backtest: bool = False) -> str:
    """Wählt genug Historie für EMA 200, ohne unnötige Gratisabrufe zu erzeugen."""

    regular = {
        "1m": "5d",
        "5m": "5d",
        "15m": "1mo",
        "30m": "1mo",
        "60m": "3mo",
        "1h": "3mo",
        "1d": "1y",
    }
    extended = {
        "1m": "7d",
        "5m": "60d",
        "15m": "60d",
        "30m": "60d",
        "60m": "2y",
        "1h": "2y",
        "1d": "2y",
    }
    periods = extended if backtest else regular
    if interval not in periods:
        raise ProviderError(f"Intervall {interval!r} wird nicht unterstützt.")
    return periods[interval]


def normalize_ohlcv(frame: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """Normalisiert yfinance- und tabellarische Daten robust auf ein OHLCV-Schema."""

    if frame is None or frame.empty:
        raise ProviderError("Die Datenquelle hat keine Kursdaten geliefert.")
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if symbol and symbol in data.columns.get_level_values(-1):
            try:
                data = data.xs(symbol, axis=1, level=-1)
            except KeyError:
                pass
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [str(column[0]) for column in data.columns]
    data.columns = [str(column).strip().lower().replace(" ", "_") for column in data.columns]
    adjusted_columns = [column for column in ("adj_close", "adjclose") if column in data.columns]
    if "close" in data.columns:
        data = data.drop(columns=adjusted_columns)
    elif adjusted_columns:
        data = data.rename(columns={adjusted_columns[0]: "close"})
    data = data.loc[:, ~data.columns.duplicated(keep="first")]
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ProviderError(f"Kursdaten unvollständig; fehlend: {', '.join(missing)}")
    data = data.loc[:, list(REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    data["volume"] = data["volume"].fillna(0.0)
    if data.empty:
        raise ProviderError("Nach der Datenbereinigung sind keine Kursdaten übrig.")
    index = pd.to_datetime(data.index, utc=True, errors="coerce")
    valid = ~index.isna()
    data = data.loc[valid]
    data.index = index[valid]
    data.index.name = "timestamp"
    return data[~data.index.duplicated(keep="last")].sort_index()


def completed_candles(
    frame: pd.DataFrame,
    interval: str,
    *,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Entfernt die noch laufende letzte Kerze anhand ihrer Startzeit."""

    duration = INTERVAL_DURATION.get(interval)
    if duration is None:
        raise ProviderError(f"Intervall {interval!r} wird nicht unterstützt.")
    current = now if now is not None else pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    completed = frame.loc[(frame.index + duration) <= current]
    if completed.empty:
        raise ProviderError("Die Datenquelle enthält noch keine abgeschlossene Kerze.")
    return completed


def validate_history(frame: pd.DataFrame, *, minimum_rows: int = 200) -> pd.DataFrame:
    """Verwirft zu kurze oder offensichtlich unbrauchbare Reihen vor einem Fallback."""

    if len(frame) < minimum_rows:
        raise ProviderError(
            f"Nur {len(frame)} abgeschlossene Kerzen geliefert; mindestens {minimum_rows} erforderlich."
        )
    if float(frame["close"].iloc[-1]) <= 0:
        raise ProviderError("Der jüngste Schlusskurs ist nicht plausibel.")
    if float(frame["volume"].iloc[-1]) <= 0:
        raise ProviderError("Die jüngste Kerze enthält kein belastbares Volumen.")
    return frame
