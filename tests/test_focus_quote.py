from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from src.data import ProviderError
from src.focus.quote import (
    TradegateQuoteProvider,
    parse_tradegate_trades,
    resample_intraday_candles,
    tradegate_day_candles,
)


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


def test_tradegate_trade_parser_ignores_allocation_rows_and_old_days():
    html = """
    <table>
      <tr><th>Date</th><th>Time</th><th>Volume</th><th>Order Volume</th><th>Price</th></tr>
      <tr><td>11/08/2026</td><td>21:59:00.000</td><td>50</td><td>&nbsp;</td><td>17.10</td></tr>
      <tr><td>12/08/2026</td><td>07:30:05.100</td><td>1 200</td><td>&nbsp;</td><td>17.50</td></tr>
      <tr class="alt"><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>1 200</td><td>17.50</td></tr>
      <tr><td>12/08/2026</td><td>07:31:10.250</td><td>100</td><td>&nbsp;</td><td>17.55</td></tr>
    </table>
    """
    trades = parse_tradegate_trades(html)

    assert len(trades) == 2
    assert list(trades["volume"]) == [1200.0, 100.0]
    assert list(trades["price"]) == [17.5, 17.55]
    assert trades.index.tz is not None
    assert trades.index[0].tz_convert("Europe/Berlin").date().isoformat() == "2026-08-12"


def test_tradegate_day_candles_fill_quiet_minutes_and_end_at_live_midpoint():
    index = pd.DatetimeIndex(
        ["2026-08-12 05:30:05+00:00", "2026-08-12 05:32:10+00:00"],
        name="timestamp",
    )
    trades = pd.DataFrame({"price": [17.5, 17.55], "volume": [1200.0, 100.0]}, index=index)
    quote = _provider({"bid": 17.58, "ask": 17.62, "last": 17.55}).quote("US26740W1099")

    candles = tradegate_day_candles(trades, quote)
    five_minutes = resample_intraday_candles(candles, 5)

    assert candles.index[0] == pd.Timestamp("2026-08-12 05:30:00+00:00")
    assert candles.index[-1] == pd.Timestamp("2026-08-12 17:15:00+00:00")
    assert candles.loc[pd.Timestamp("2026-08-12 05:31:00+00:00"), "volume"] == 0
    assert candles["close"].iloc[-1] == pytest.approx(17.6)
    assert five_minutes["close"].iloc[-1] == pytest.approx(17.6)
