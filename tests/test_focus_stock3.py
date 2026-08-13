from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.focus.stock3 import Stock3LangSchwarzProvider, decode_stock3_candles, parse_stock3_quote


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _quote_payload() -> dict[str, object]:
    return {
        "data": {
            "quotations": [
                {
                    "exchange": {"id": 22, "name": "Lang & Schwarz"},
                    "bid": {
                        "value": 18.04,
                        "time": "2026-08-13T20:03:00Z",
                        "prevClose": 17.52,
                        "high": 18.83,
                        "low": 17.73,
                    },
                    "ask": {"value": 18.115, "time": "2026-08-13T20:03:00Z"},
                }
            ]
        }
    }


def _history_payload() -> dict[str, object]:
    return {
        "data": {
            "exponent": 3,
            "ts": [1, 1],
            "o": [10_000, 100],
            "h": [100, 50],
            "c": [50, 25],
            "l": [50, 30],
        },
        "dataRT": {
            "ts": [1],
            "o": [-25],
            "h": [75],
            "c": [50],
            "l": [25],
        },
    }


def test_stock3_quote_selects_lang_schwarz_bid():
    fetched_at = datetime(2026, 8, 13, 20, 3, 5, tzinfo=UTC)

    quote = parse_stock3_quote(_quote_payload(), fetched_at=fetched_at)

    assert quote.venue == "Lang & Schwarz"
    assert quote.bid == pytest.approx(18.04)
    assert quote.ask == pytest.approx(18.115)
    assert quote.last == quote.bid
    assert quote.change_percent == pytest.approx((18.04 / 17.52 - 1) * 100)
    assert quote.quoted_at == datetime(2026, 8, 13, 20, 3, tzinfo=UTC)


def test_stock3_delta_history_decodes_ohlc_and_realtime_tail():
    candles = decode_stock3_candles(_history_payload(), 60)

    assert list(candles.columns) == ["open", "high", "low", "close", "volume"]
    assert len(candles) == 3
    assert candles.index.tz == UTC
    assert candles.iloc[0].to_dict() == pytest.approx(
        {"open": 10.0, "high": 10.1, "low": 9.95, "close": 10.05, "volume": 0.0}
    )
    assert candles.iloc[1].to_dict() == pytest.approx(
        {"open": 10.15, "high": 10.2, "low": 10.12, "close": 10.175, "volume": 0.0}
    )
    assert candles.iloc[2].to_dict() == pytest.approx(
        {"open": 10.15, "high": 10.225, "low": 10.125, "close": 10.175, "volume": 0.0}
    )
    assert candles.attrs["provider"] == "stock3 · L&S Bid"


def test_stock3_provider_requests_bid_history_from_lang_schwarz():
    requested_urls: list[str] = []

    def opener(request, **_kwargs):
        requested_urls.append(request.full_url)
        payload = _quote_payload() if "/instrument/" in request.full_url else _history_payload()
        return _Response(payload)

    provider = Stock3LangSchwarzProvider(
        opener=opener,
        clock=lambda: datetime(2026, 8, 13, 20, 3, 5, tzinfo=UTC),
    )

    assert provider.quote().bid == pytest.approx(18.04)
    assert len(provider.history(300)) == 3
    assert "iid=61824087" in requested_urls[1]
    assert "res=300" in requested_urls[1]
    assert "qs=bid" in requested_urls[1]
    assert "eid=22" in requested_urls[1]


def test_week_defaults_to_thirty_minute_candles():
    from src.focus.display import DEFAULT_INTERVAL, PERIOD_INTERVALS

    assert DEFAULT_INTERVAL["1W"] == 30
    assert PERIOD_INTERVALS["1W"][0] == 5
