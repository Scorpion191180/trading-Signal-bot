"""Gemeinsame Livekursmodelle und die Tradegate-Ersatzquelle."""

from __future__ import annotations

import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi
import pandas as pd

from src.data import ProviderError


@dataclass(frozen=True)
class LiveQuote:
    provider: str
    venue: str
    isin: str
    bid: float
    ask: float
    bid_size: float | None
    ask_size: float | None
    last: float | None
    high: float | None
    low: float | None
    change_percent: float | None
    volume: float | None
    fetched_at: datetime
    refresh_seconds: int
    quoted_at: datetime | None = None

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_percent(self) -> float:
        return (self.spread / self.midpoint) * 100


class _TradeTableParser(HTMLParser):
    """Extrahiert ausschließlich die Hauptzeilen der Umsatzliste."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_tradegate_trades(html: str) -> pd.DataFrame:
    """Liest Datum, Uhrzeit, Stückzahl und Preis aus der offiziellen Umsatzseite."""

    parser = _TradeTableParser()
    parser.feed(html)
    records: list[tuple[datetime, float, float]] = []
    berlin = ZoneInfo("Europe/Berlin")
    for cells in parser.rows:
        if len(cells) < 5 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[0]):
            continue
        try:
            timestamp = datetime.strptime(f"{cells[0]} {cells[1]}", "%d/%m/%Y %H:%M:%S.%f")
            timestamp = timestamp.replace(tzinfo=berlin).astimezone(UTC)
            volume = float(re.sub(r"\s+", "", cells[2]).replace(",", "."))
            price = float(re.sub(r"\s+", "", cells[4]).replace(",", "."))
        except (ValueError, IndexError):
            continue
        if volume > 0 and price > 0:
            records.append((timestamp, price, volume))
    if not records:
        raise ProviderError("Tradegate hat keine Tagesumsätze geliefert.")
    data = pd.DataFrame(records, columns=["timestamp", "price", "volume"]).set_index("timestamp")
    data.index = pd.DatetimeIndex(data.index, tz="UTC", name="timestamp")
    data = data[~data.index.duplicated(keep="last")].sort_index()
    local_dates = pd.Series(data.index.tz_convert(berlin).date, index=data.index)
    latest_date = local_dates.max()
    result = data.loc[local_dates == latest_date]
    result.attrs["provider"] = "Tradegate BSX Umsätze"
    return result


def market_day_candles(trades: pd.DataFrame, quote: LiveQuote) -> pd.DataFrame:
    """Baut lückenlose Ein-Minuten-Kerzen des gelieferten deutschen Handelsplatzes."""

    if trades.empty:
        raise ProviderError(f"{quote.venue} hat keine Tagesumsätze geliefert.")
    berlin = ZoneInfo("Europe/Berlin")
    local_index = trades.index.tz_convert(berlin)
    trading_date = local_index[-1].date()
    quote_timestamp = quote.quoted_at or quote.fetched_at
    quote_date = quote_timestamp.astimezone(berlin).date()
    last_trade_minute = trades.index[-1].floor("min")
    quote_minute = pd.Timestamp(quote_timestamp).floor("min")
    session_close = time(23, 0) if quote.venue == "Lang & Schwarz" else time(22, 0)
    session_end = pd.Timestamp(
        datetime.combine(trading_date, session_close, tzinfo=berlin).astimezone(UTC)
    )
    quote_minute = min(quote_minute, session_end)
    end = max(last_trade_minute, quote_minute) if quote_date == trading_date else last_trade_minute

    grouped = trades.resample("1min", label="left", closed="left")
    candles = grouped.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "sum"),
    )
    full_index = pd.date_range(candles.index[0], end, freq="1min", tz="UTC", name="timestamp")
    candles = candles.reindex(full_index)
    candles["close"] = candles["close"].ffill().bfill()
    for column in ("open", "high", "low"):
        candles[column] = candles[column].fillna(candles["close"])
    candles["volume"] = candles["volume"].fillna(0.0)

    live_price = quote.midpoint
    last_index = candles.index[-1]
    previous_close = float(candles["close"].iloc[-2]) if len(candles) > 1 else live_price
    candles.loc[last_index, "open"] = float(candles.loc[last_index, "open"] or previous_close)
    candles.loc[last_index, "high"] = max(float(candles.loc[last_index, "high"]), live_price)
    candles.loc[last_index, "low"] = min(float(candles.loc[last_index, "low"]), live_price)
    candles.loc[last_index, "close"] = live_price
    candles.attrs["provider"] = f"{quote.venue} Abschlüsse + Livequote"
    candles.attrs["last_trade_timestamp"] = trades.index[-1].isoformat()
    return candles[["open", "high", "low", "close", "volume"]]


def tradegate_day_candles(trades: pd.DataFrame, quote: LiveQuote) -> pd.DataFrame:
    """Kompatibilitätsname für bestehende Aufrufer und Tests."""

    return market_day_candles(trades, quote)


def resample_intraday_candles(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Verdichtet Minutenkerzen einschließlich der laufenden Livekerze."""

    grouped = frame.resample(f"{minutes}min", label="left", closed="left")
    result = grouped.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna(subset=["open", "high", "low", "close"])
    result.attrs.update(frame.attrs)
    return result


def _number(payload: dict[str, Any], key: str, *, required: bool = False) -> float | None:
    value = payload.get(key)
    if value is None or value in {"", "./.", "-"}:
        if required:
            raise ProviderError(f"Tradegate-Antwort enthält keinen gültigen Wert für {key}.")
        return None
    try:
        if isinstance(value, str):
            value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"Tradegate-Wert {key} ist nicht lesbar.") from exc
    if required and parsed <= 0:
        raise ProviderError(f"Tradegate-Wert {key} ist nicht plausibel.")
    return parsed


class TradegateQuoteProvider:
    """Liest das öffentliche Tradegate-Level-1-Snapshotformat."""

    name = "Tradegate BSX Level 1"
    venue = "Tradegate BSX"
    endpoint = "https://www.tradegatebsx.com/refresh.php"
    trades_endpoint = "https://www.tradegatebsx.com/orderbuch_umsaetze.php"

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], datetime] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._opener = opener
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ssl_context = ssl_context or ssl.create_default_context(cafile=certifi.where())

    def quote(self, isin: str) -> LiveQuote:
        normalized_isin = isin.upper().strip()
        if len(normalized_isin) != 12 or not normalized_isin.isalnum():
            raise ProviderError("Die ISIN für den Tradegate-Abruf ist ungültig.")
        request = Request(
            f"{self.endpoint}?{urlencode({'isin': normalized_isin})}",
            headers={
                "Accept": "application/json",
                "User-Agent": "DWave-Kurzfrist-Signal/0.3 (private market-data display)",
            },
        )
        try:
            with self._opener(request, timeout=8, context=self._ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Tradegate-Livekurs ist nicht erreichbar: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Tradegate hat kein gültiges Kursformat geliefert.") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Tradegate hat kein gültiges Kursobjekt geliefert.")

        bid = _number(payload, "bid", required=True)
        ask = _number(payload, "ask", required=True)
        assert bid is not None and ask is not None
        if ask < bid:
            raise ProviderError("Tradegate meldet einen unplausiblen Geld-/Briefkurs.")
        refresh_value = _number(payload, "refresh")
        refresh_seconds = max(int(refresh_value or 10), 5)
        return LiveQuote(
            provider=self.name,
            venue=self.venue,
            isin=normalized_isin,
            bid=bid,
            ask=ask,
            bid_size=_number(payload, "bidsize"),
            ask_size=_number(payload, "asksize"),
            last=_number(payload, "last"),
            high=_number(payload, "high"),
            low=_number(payload, "low"),
            change_percent=_number(payload, "delta"),
            volume=_number(payload, "stueck"),
            fetched_at=self._clock().astimezone(UTC),
            refresh_seconds=refresh_seconds,
        )

    def trades(self, isin: str) -> pd.DataFrame:
        normalized_isin = isin.upper().strip()
        if len(normalized_isin) != 12 or not normalized_isin.isalnum():
            raise ProviderError("Die ISIN für den Tradegate-Abruf ist ungültig.")
        request = Request(
            f"{self.trades_endpoint}?{urlencode({'isin': normalized_isin, 'lang': 'en'})}",
            headers={
                "Accept": "text/html",
                "User-Agent": "DWave-Kurzfrist-Signal/0.4 (private market-data display)",
            },
        )
        try:
            with self._opener(request, timeout=12, context=self._ssl_context) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Tradegate-Tagesumsätze sind nicht erreichbar: {exc}") from exc
        return parse_tradegate_trades(html)
