"""Öffentliche L&S-Geld-/Briefkurse des frei sichtbaren stock3-D-Wave-Charts."""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
import pandas as pd

from src.data import ProviderError

from .quote import LiveQuote

STOCK3_INSTRUMENT_ID = 61824087
LANG_SCHWARZ_EXCHANGE_ID = 22
SUPPORTED_RESOLUTIONS = {60, 300, 1800, 3600, 86400}
DEFAULT_HISTORY_CACHE = Path(__file__).resolve().parents[2] / "data" / "stock3_cache"


def _number(value: object, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"stock3 liefert keinen gültigen Wert für {field}.") from exc
    if not pd.notna(parsed):
        raise ProviderError(f"stock3 liefert keinen gültigen Wert für {field}.")
    return parsed


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ProviderError("stock3 liefert keinen gültigen L&S-Kurszeitpunkt.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise ProviderError("stock3 liefert keinen gültigen L&S-Kurszeitpunkt.") from exc


def parse_stock3_quote(payload: dict[str, Any], *, fetched_at: datetime) -> LiveQuote:
    """Liest ausschließlich die L&S-Quotation mit Börsen-ID 22."""

    data = payload.get("data")
    quotations = data.get("quotations") if isinstance(data, dict) else None
    if not isinstance(quotations, list):
        raise ProviderError("stock3 liefert keine lesbaren Handelsplätze.")
    quotation = next(
        (
            item
            for item in quotations
            if isinstance(item, dict)
            and isinstance(item.get("exchange"), dict)
            and item["exchange"].get("id") == LANG_SCHWARZ_EXCHANGE_ID
        ),
        None,
    )
    if quotation is None:
        raise ProviderError("stock3 liefert aktuell keinen L&S-Kurs für D-Wave.")
    bid_data = quotation.get("bid")
    ask_data = quotation.get("ask")
    if not isinstance(bid_data, dict) or not isinstance(ask_data, dict):
        raise ProviderError("stock3 liefert keinen vollständigen L&S-Geld-/Briefkurs.")
    bid = _number(bid_data.get("value"), field="Geld")
    ask = _number(ask_data.get("value"), field="Brief")
    if bid <= 0 or ask < bid:
        raise ProviderError("stock3 meldet einen unplausiblen L&S-Geld-/Briefkurs.")
    previous_close = _number(bid_data.get("prevClose"), field="Vortag")
    change_percent = (bid / previous_close - 1) * 100 if previous_close > 0 else None
    return LiveQuote(
        provider="stock3 öffentlicher L&S-Kurs",
        venue="Lang & Schwarz",
        isin="US26740W1099",
        bid=bid,
        ask=ask,
        bid_size=None,
        ask_size=None,
        last=bid,
        high=_number(bid_data.get("high"), field="Tageshoch"),
        low=_number(bid_data.get("low"), field="Tagestief"),
        change_percent=change_percent,
        volume=None,
        fetched_at=fetched_at.astimezone(UTC),
        refresh_seconds=10,
        quoted_at=_timestamp(bid_data.get("time")),
    )


def decode_stock3_candles(
    payload: dict[str, Any],
    resolution_seconds: int,
    *,
    quote_type: str = "bid",
) -> pd.DataFrame:
    """Dekodiert eine öffentlich ausgelieferte, differenzkomprimierte L&S-Reihe."""

    if resolution_seconds not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Diese stock3-Auflösung wird nicht unterstützt.")
    if quote_type not in {"bid", "ask"}:
        raise ValueError("stock3 unterstützt hier nur Geld- oder Briefkurse.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProviderError("stock3 liefert keine L&S-Chartdaten.")
    exponent = int(_number(data.get("exponent"), field="Kursgenauigkeit"))
    scale = 10**exponent
    timestamp_ms = 0.0
    previous_close_units = 0.0
    records: list[tuple[pd.Timestamp, float, float, float, float, float]] = []
    for block_name in ("data", "dataRT"):
        block = payload.get(block_name)
        if not isinstance(block, dict):
            continue
        arrays = [block.get(key) for key in ("ts", "o", "h", "c", "l")]
        if not all(isinstance(values, list) for values in arrays):
            continue
        times, opens, highs, closes, lows = arrays
        assert all(isinstance(values, list) for values in (times, opens, highs, closes, lows))
        row_count = min(len(times), len(opens), len(highs), len(closes), len(lows))
        for index in range(row_count):
            time_delta = _number(times[index], field="Zeitdifferenz")
            if time_delta <= 0:
                continue
            timestamp_ms += time_delta * resolution_seconds * 1000
            previous_close_units += _number(opens[index], field="Eröffnung")
            high_delta = _number(highs[index], field="Hoch")
            close_delta = _number(closes[index], field="Schluss")
            low_delta = _number(lows[index], field="Tief")
            open_value = previous_close_units / scale
            high_value = (previous_close_units + high_delta) / scale
            low_value = (previous_close_units - low_delta) / scale
            close_value = (previous_close_units + high_delta - close_delta) / scale
            previous_close_units += high_delta - close_delta
            records.append(
                (
                    pd.to_datetime(timestamp_ms, unit="ms", utc=True),
                    open_value,
                    high_value,
                    low_value,
                    close_value,
                    0.0,
                )
            )
    if not records:
        raise ProviderError("stock3 liefert keine dekodierbaren L&S-Bid-Kerzen.")
    frame = pd.DataFrame(
        records,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    ).set_index("timestamp")
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True), name="timestamp")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if (
        (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
        or (frame[["open", "high", "low", "close"]] <= 0).any().any()
    ):
        raise ProviderError("stock3 liefert unplausible L&S-Kerzen.")
    label = "Bid" if quote_type == "bid" else "Ask"
    frame.attrs["provider"] = f"stock3 · L&S {label}"
    frame.attrs["quote_type"] = quote_type
    return frame


class Stock3LangSchwarzProvider:
    """Ruft den ohne Anmeldung sichtbaren D-Wave-Chart von stock3 ab."""

    quote_endpoint = f"https://api.stock3.com/instrument/{STOCK3_INSTRUMENT_ID}"
    chart_endpoint = "https://charting.stock3.com/d/q"

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], datetime] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        cache_directory: Path | None = None,
    ) -> None:
        self._opener = opener
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ssl_context = ssl_context or ssl.create_default_context(cafile=certifi.where())
        self._cache_directory = (
            cache_directory
            if cache_directory is not None
            else DEFAULT_HISTORY_CACHE
            if opener is urlopen
            else None
        )

    def _cache_path(self, resolution_seconds: int, quote_type: str) -> Path | None:
        if self._cache_directory is None:
            return None
        return self._cache_directory / f"dwave_ls_{quote_type}_{resolution_seconds}.csv"

    def _write_history_cache(
        self,
        frame: pd.DataFrame,
        resolution_seconds: int,
        quote_type: str,
    ) -> None:
        path = self._cache_path(resolution_seconds, quote_type)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".csv.tmp")
            frame.to_csv(temporary, index_label="timestamp")
            temporary.replace(path)
        except OSError:
            return

    def _read_history_cache(self, resolution_seconds: int, quote_type: str) -> pd.DataFrame | None:
        path = self._cache_path(resolution_seconds, quote_type)
        if path is None or not path.is_file():
            return None
        try:
            frame = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True), name="timestamp")
            required = ["open", "high", "low", "close", "volume"]
            frame = frame[required].astype(float).sort_index()
        except (OSError, ValueError, KeyError, pd.errors.ParserError):
            return None
        if frame.empty or (
            (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
            or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
            or (frame[["open", "high", "low", "close"]] <= 0).any().any()
        ):
            return None
        label = "Bid" if quote_type == "bid" else "Ask"
        frame.attrs["provider"] = f"stock3 · L&S {label} · lokaler Cache"
        frame.attrs["quote_type"] = quote_type
        frame.attrs["cached"] = True
        return frame

    def _read_json(self, url: str, *, label: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "de-DE,de;q=0.9",
                "User-Agent": "DWave-Kurzfrist-Signal/0.9 (private market-data display)",
            },
        )
        try:
            with self._opener(request, timeout=20, context=self._ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"{label} ist nicht erreichbar: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{label} liefert kein gültiges Datenformat.") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"{label} liefert kein gültiges Datenobjekt.")
        return payload

    def quote(self) -> LiveQuote:
        select = (
            "id,name,quotations[exchange[id,name],defaultQuoteType,"
            "bid[value,time,prevClose,open,high,low,change],"
            "ask[value,time,prevClose,open,high,low,change]]"
        )
        url = f"{self.quote_endpoint}?{urlencode({'client_id': 'stock3', 'select': select})}"
        payload = self._read_json(url, label="Der öffentliche stock3-L&S-Kurs")
        return parse_stock3_quote(payload, fetched_at=self._clock())

    def history(self, resolution_seconds: int, *, quote_type: str = "bid") -> pd.DataFrame:
        if resolution_seconds not in SUPPORTED_RESOLUTIONS:
            raise ValueError("Diese stock3-Auflösung wird nicht unterstützt.")
        if quote_type not in {"bid", "ask"}:
            raise ValueError("stock3 unterstützt hier nur Geld- oder Briefkurse.")
        query = urlencode(
            {
                "iid": STOCK3_INSTRUMENT_ID,
                "res": resolution_seconds,
                "qs": quote_type,
                "eid": LANG_SCHWARZ_EXCHANGE_ID,
                "client_id": "stock3",
                "locale": "de",
            }
        )
        try:
            payload = self._read_json(
                f"{self.chart_endpoint}?{query}",
                label=f"Die öffentliche stock3-L&S-{quote_type.upper()}-Historie",
            )
        except ProviderError:
            cached = self._read_history_cache(resolution_seconds, quote_type)
            if cached is not None:
                return cached
            raise
        frame = decode_stock3_candles(payload, resolution_seconds, quote_type=quote_type)
        self._write_history_cache(frame, resolution_seconds, quote_type)
        return frame
