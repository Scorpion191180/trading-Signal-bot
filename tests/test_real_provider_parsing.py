from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from src.data import (
    AlpacaMarketDataProvider,
    MarketDataRequest,
    TwelveDataMarketDataProvider,
    alpaca_provider,
    twelve_data_provider,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_alpaca_parses_real_bar_schema_without_putting_secrets_in_url(monkeypatch):
    index = pd.date_range(end=datetime.now(UTC) - timedelta(days=2), periods=205, freq="D")
    bars = [
        {"t": timestamp.isoformat(), "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000}
        for timestamp in index
    ]
    captured_url = ""

    def fake_urlopen(request, timeout):
        nonlocal captured_url
        captured_url = request.full_url
        assert timeout == 15
        return FakeResponse({"bars": bars, "symbol": "AAPL", "next_page_token": None})

    monkeypatch.setattr(alpaca_provider, "urlopen", fake_urlopen)
    provider = AlpacaMarketDataProvider("key-id", "top-secret")
    frame = provider.history(MarketDataRequest("AAPL", "1d", "1y"))

    assert len(frame) == 205
    assert frame.attrs["provider"] == "Alpaca (IEX)"
    assert "top-secret" not in captured_url
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


def test_twelve_data_parses_real_time_series_schema(monkeypatch):
    index = pd.date_range(end=datetime.now(UTC) - timedelta(days=2), periods=205, freq="D")
    values = [
        {
            "datetime": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": "100",
            "high": "102",
            "low": "99",
            "close": "101",
            "volume": "1000",
        }
        for timestamp in reversed(index)
    ]

    def fake_urlopen(request, timeout):
        assert "twelve-secret" not in request.full_url
        assert timeout == 15
        return FakeResponse({"meta": {"symbol": "AAPL"}, "values": values, "status": "ok"})

    monkeypatch.setattr(twelve_data_provider, "urlopen", fake_urlopen)
    provider = TwelveDataMarketDataProvider("twelve-secret")
    frame = provider.history(MarketDataRequest("AAPL", "1d", "1y"))

    assert len(frame) == 205
    assert frame.attrs["provider"] == "Twelve Data"
    assert frame.index.is_monotonic_increasing
