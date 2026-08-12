"""Kostenloser Alpaca-IEX-Feed als optionale echte Rückfallebene für US-Aktien."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .base import MarketDataRequest, ProviderError, completed_candles, normalize_ohlcv, validate_history


class AlpacaMarketDataProvider:
    name = "Alpaca (IEX)"
    is_demo = False
    interval_map = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "60m": "1Hour",
        "1h": "1Hour",
        "1d": "1Day",
    }
    period_days = {"5d": 7, "7d": 10, "1mo": 35, "3mo": 100, "60d": 90, "1y": 370, "2y": 740}

    def __init__(self, api_key_id: str, api_secret_key: str) -> None:
        self.api_key_id = api_key_id.strip()
        self.api_secret_key = api_secret_key.strip()
        if not self.api_key_id or not self.api_secret_key:
            raise ValueError("Für Alpaca fehlen APCA_API_KEY_ID und APCA_API_SECRET_KEY.")

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        timeframe = self.interval_map.get(request.interval)
        if timeframe is None:
            raise ProviderError(f"Intervall {request.interval!r} wird von Alpaca nicht unterstützt.")
        days = self.period_days.get(request.period)
        if days is None:
            raise ProviderError(f"Zeitraum {request.period!r} wird von Alpaca nicht unterstützt.")
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        params = urlencode(
            {
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 10000,
                "adjustment": "raw",
                "feed": "iex",
            }
        )
        symbol = quote(request.symbol.upper().strip(), safe="")
        http_request = Request(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?{params}",
            headers={
                "APCA-API-KEY-ID": self.api_key_id,
                "APCA-API-SECRET-KEY": self.api_secret_key,
                "User-Agent": "trading-signal-agent/0.1",
            },
        )
        try:
            with urlopen(http_request, timeout=15) as response:  # noqa: S310 - feste HTTPS-Domain
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ProviderError(f"Alpaca antwortet mit HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Alpaca konnte nicht geladen werden: {exc}") from exc
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ProviderError(f"Alpaca liefert keine Kursreihe: {payload.get('message', 'keine Bars')}")
        frame = pd.DataFrame(bars).rename(
            columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        )
        frame = frame.set_index("timestamp")
        normalized = normalize_ohlcv(frame, request.symbol)
        result = validate_history(
            completed_candles(normalized, request.interval),
            minimum_rows=request.minimum_rows,
            require_latest_volume=request.require_latest_volume,
        )
        result.attrs["provider"] = self.name
        return result
