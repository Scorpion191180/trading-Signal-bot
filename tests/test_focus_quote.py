from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.data import ProviderError
from src.focus.quote import TradegateQuoteProvider


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _provider(payload: dict[str, object]) -> TradegateQuoteProvider:
    fetched_at = datetime(2026, 8, 12, 17, 15, 0, tzinfo=UTC)

    def opener(request, timeout, context):
        assert request.full_url.endswith("isin=US26740W1099")
        assert timeout == 8
        assert context is not None
        return FakeResponse(payload)

    return TradegateQuoteProvider(opener=opener, clock=lambda: fetched_at)


def test_tradegate_quote_parses_level_one_snapshot_and_spread():
    quote = _provider(
        {
            "bid": 17.86,
            "ask": 17.885,
            "bidsize": 5000,
            "asksize": 5000,
            "last": 17.805,
            "high": 17.95,
            "low": 17.45,
            "delta": 1.57,
            "stueck": 161681,
            "refresh": 10,
        }
    ).quote("us26740w1099")

    assert quote.provider == "Tradegate BSX Level 1"
    assert quote.bid == 17.86
    assert quote.ask == 17.885
    assert quote.midpoint == pytest.approx(17.8725)
    assert quote.spread == pytest.approx(0.025)
    assert quote.spread_percent == pytest.approx(0.13988, rel=1e-4)
    assert quote.volume == 161681
    assert quote.fetched_at == datetime(2026, 8, 12, 17, 15, 0, tzinfo=UTC)


def test_tradegate_quote_accepts_missing_optional_values():
    quote = _provider({"bid": "17,80", "ask": "17,90", "last": "./.", "refresh": 3}).quote(
        "US26740W1099"
    )
    assert quote.bid == 17.8
    assert quote.ask == 17.9
    assert quote.last is None
    assert quote.refresh_seconds == 5


def test_tradegate_quote_rejects_crossed_market():
    provider = _provider({"bid": 18.0, "ask": 17.9})
    with pytest.raises(ProviderError, match="unplausiblen Geld-/Briefkurs"):
        provider.quote("US26740W1099")
