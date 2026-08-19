"""Öffentliche Lang-&-Schwarz-Kurse für die fokussierte D-Wave-Ansicht."""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi
import pandas as pd

from src.data import ProviderError

from .quote import LiveQuote

BERLIN = ZoneInfo("Europe/Berlin")
TIME_PATTERN = re.compile(r"\d{2}:\d{2}:\d{2}(?:\.\d{3})?")


@dataclass(frozen=True)
class LangSchwarzSnapshot:
    quote: LiveQuote
    trades: pd.DataFrame


class _PageParser(HTMLParser):
    """Sammelt sichtbare Texte sowie Tabellenzeilen ohne externe HTML-Abhängigkeit."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[str] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(data.split())
        if normalized:
            self.tokens.append(normalized)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _german_number(value: str) -> float:
    normalized = (
        value.replace("\xa0", "")
        .replace("€", "")
        .replace("%", "")
        .replace("Stück", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    return float(normalized)


def _quote_date(fetched_at: datetime, displayed_time: time) -> date:
    local_fetch = fetched_at.astimezone(BERLIN)
    candidate = datetime.combine(local_fetch.date(), displayed_time, tzinfo=BERLIN)
    if candidate > local_fetch + timedelta(minutes=5):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate.date()


def _find_token(tokens: list[str], value: str, start: int) -> int:
    try:
        return tokens.index(value, start)
    except ValueError as exc:
        raise ProviderError(f"Lang & Schwarz liefert kein Feld '{value}'.") from exc


def _next_number(tokens: list[str], start: int, *, require_euro: bool = False) -> float:
    for token in tokens[start:]:
        if require_euro and "€" not in token:
            continue
        try:
            return _german_number(token)
        except ValueError:
            continue
    raise ProviderError("Lang & Schwarz liefert keinen lesbaren Kurswert.")


def parse_lang_schwarz_page(
    html: str,
    *,
    isin: str,
    fetched_at: datetime,
) -> LangSchwarzSnapshot:
    """Liest Livequote und heutige Abschlüsse aus der offiziellen L&S-Instrumentseite."""

    parser = _PageParser()
    parser.feed(html)
    marker = next(
        (index for index, token in enumerate(parser.tokens) if f"ISIN: {isin}" in token),
        None,
    )
    if marker is None:
        raise ProviderError("Lang & Schwarz hat die erwartete D-Wave-ISIN nicht geliefert.")

    bid_marker = _find_token(parser.tokens, "Geld", marker)
    ask_marker = _find_token(parser.tokens, "Brief", bid_marker)
    performance_marker = _find_token(parser.tokens, "Performance", ask_marker)
    if performance_marker - marker > 40:
        raise ProviderError("Die Lang-&-Schwarz-Kursfelder sind nicht plausibel angeordnet.")

    bid = _next_number(parser.tokens, bid_marker + 1, require_euro=True)
    ask = _next_number(parser.tokens, ask_marker + 1, require_euro=True)
    if bid <= 0 or ask <= 0 or ask < bid:
        raise ProviderError("Lang & Schwarz meldet einen unplausiblen Geld-/Briefkurs.")
    last = _next_number(parser.tokens, marker + 1, require_euro=True)

    quote_time_text = next(
        (token for token in parser.tokens[marker:bid_marker] if re.fullmatch(r"\d{2}:\d{2}:\d{2}", token)),
        None,
    )
    if quote_time_text is None:
        raise ProviderError("Lang & Schwarz liefert keinen Kurszeitpunkt.")
    displayed_time = datetime.strptime(quote_time_text, "%H:%M:%S").time()
    trading_date = _quote_date(fetched_at, displayed_time)
    quoted_at = datetime.combine(trading_date, displayed_time, tzinfo=BERLIN).astimezone(UTC)

    changes = [
        _german_number(token)
        for token in parser.tokens[marker:bid_marker]
        if "%" in token
    ]
    bid_size = _next_number(parser.tokens, bid_marker + 2)
    ask_size = _next_number(parser.tokens, ask_marker + 2)

    records: list[tuple[datetime, float, float]] = []
    for cells in parser.rows:
        if len(cells) < 4 or not TIME_PATTERN.fullmatch(cells[0]) or "€" not in cells[1]:
            continue
        try:
            trade_time = datetime.strptime(cells[0], "%H:%M:%S.%f").time()
            price = _german_number(cells[1])
            volume = _german_number(cells[3])
        except ValueError:
            continue
        if price > 0 and volume > 0:
            timestamp = datetime.combine(trading_date, trade_time, tzinfo=BERLIN).astimezone(UTC)
            records.append((timestamp, price, volume))
    if not records:
        raise ProviderError("Lang & Schwarz hat keine heutigen D-Wave-Abschlüsse geliefert.")

    trades = pd.DataFrame(records, columns=["timestamp", "price", "volume"]).set_index("timestamp")
    trades.index = pd.DatetimeIndex(trades.index, tz="UTC", name="timestamp")
    trades = trades[~trades.index.duplicated(keep="last")].sort_index()
    trades.attrs["provider"] = "Lang & Schwarz Abschlüsse"

    quote = LiveQuote(
        provider="Lang & Schwarz öffentliche Instrumentseite",
        venue="Lang & Schwarz",
        isin=isin,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        last=last,
        high=float(trades["price"].max()),
        low=float(trades["price"].min()),
        change_percent=changes[-1] if changes else None,
        volume=float(trades["volume"].sum()),
        fetched_at=fetched_at.astimezone(UTC),
        refresh_seconds=10,
        quoted_at=quoted_at,
    )
    return LangSchwarzSnapshot(quote=quote, trades=trades)


class LangSchwarzQuoteProvider:
    """Liest D-Wave privat aus der öffentlichen L&S-Instrumentseite."""

    name = "Lang & Schwarz öffentliche Instrumentseite"
    venue = "Lang & Schwarz"
    endpoint = "https://www.ls-tc.de/de/aktie/1875100"

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

    def snapshot(self, isin: str) -> LangSchwarzSnapshot:
        normalized_isin = isin.upper().strip()
        if len(normalized_isin) != 12 or not normalized_isin.isalnum():
            raise ProviderError("Die ISIN für den Lang-&-Schwarz-Abruf ist ungültig.")
        request = Request(
            self.endpoint,
            headers={
                "Accept": "text/html",
                "Accept-Language": "de-DE,de;q=0.9",
                "User-Agent": "DWave-Kurzfrist-Signal/0.5 (private market-data display)",
            },
        )
        try:
            with self._opener(request, timeout=12, context=self._ssl_context) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Lang & Schwarz ist nicht erreichbar: {exc}") from exc
        return parse_lang_schwarz_page(
            html,
            isin=normalized_isin,
            fetched_at=self._clock().astimezone(UTC),
        )
