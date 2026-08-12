"""Aktueller, handelbarer D-Wave-Kurs von Tradegate BSX."""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

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

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_percent(self) -> float:
        return (self.spread / self.midpoint) * 100


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
