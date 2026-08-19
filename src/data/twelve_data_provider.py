"""Optionale kostenlose Twelve-Data-Rückfallebene mit persönlichem API-Schlüssel."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .base import MarketDataRequest, ProviderError, completed_candles, normalize_ohlcv, validate_history


class TwelveDataMarketDataProvider:
    name = "Twelve Data"
    is_demo = False
    supported_intervals = {"1m", "5m", "15m", "30m", "60m", "1h", "1d"}
    interval_map = {"60m": "1h", "1d": "1day"}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("Für Twelve Data fehlt TWELVE_DATA_API_KEY.")

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        if request.interval not in self.supported_intervals:
            raise ProviderError(f"Intervall {request.interval!r} wird von Twelve Data nicht unterstützt.")
        params = urlencode(
            {
                "symbol": request.symbol.upper().strip(),
                "interval": self.interval_map.get(request.interval, request.interval),
                "outputsize": 5000,
                "format": "JSON",
                "timezone": "UTC",
            }
        )
        http_request = Request(
            f"https://api.twelvedata.com/time_series?{params}",
            headers={"Authorization": f"apikey {self.api_key}", "User-Agent": "trading-signal-agent/0.1"},
        )
        try:
            with urlopen(http_request, timeout=15) as response:  # noqa: S310 - feste HTTPS-Domain
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ProviderError(f"Twelve Data antwortet mit HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Twelve Data konnte nicht geladen werden: {exc}") from exc
        if payload.get("status") == "error" or not isinstance(payload.get("values"), list):
            message = str(payload.get("message") or "keine Kursreihe geliefert")
            raise ProviderError(f"Twelve Data: {message}")
        frame = pd.DataFrame(payload["values"])
        if "datetime" not in frame:
            raise ProviderError("Twelve Data liefert keine Zeitstempel.")
        frame = frame.set_index("datetime")
        normalized = normalize_ohlcv(frame, request.symbol)
        result = validate_history(
            completed_candles(normalized, request.interval),
            minimum_rows=request.minimum_rows,
            require_latest_volume=request.require_latest_volume,
        )
        result.attrs["provider"] = self.name
        return result
