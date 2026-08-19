from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.focus.lang_schwarz import (
    LangSchwarzQuoteProvider,
    parse_lang_schwarz_page,
)
from src.focus.quote import market_day_candles

HTML = """
<html><body>
  <h3>D-WAVE QUANTUM DL-,0001</h3>
  <div>ISIN: US26740W1099 | WKN: A3DSV9</div>
  <span>17,9350 €</span><span>+0,4050</span><span>+2,31 %</span><span>22:44:55</span>
  <span>Status:</span><span>tradeable</span>
  <div>Geld</div><span>17,8900 €</span><span>Stück:</span><span>572</span>
  <div>Brief</div><span>17,9800 €</span><span>Stück:</span><span>572</span>
  <h3>Performance</h3>
  <h3>Trades</h3>
  <table>
    <tr><th>Zeit</th><th>Kurs</th><th></th><th>Volumen</th></tr>
    <tr><td>21:59:34.234</td><td>18,00 €</td><td></td><td>200</td></tr>
    <tr><td>19:54:29.309</td><td>17,915 €</td><td></td><td>6</td></tr>
    <tr><td>07:30:34.611</td><td>17,655 €</td><td></td><td>9</td></tr>
  </table>
  <h3>Quotes</h3>
  <table>
    <tr><td>22:44:55.000</td><td>572</td><td>17,8900 €</td><td>17,9800 €</td><td>572</td></tr>
  </table>
</body></html>
"""


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return HTML.encode()


def test_lang_schwarz_page_parses_quote_and_full_day_trades():
    fetched_at = datetime(2026, 8, 12, 20, 45, tzinfo=UTC)
    snapshot = parse_lang_schwarz_page(
        HTML,
        isin="US26740W1099",
        fetched_at=fetched_at,
    )

    assert snapshot.quote.venue == "Lang & Schwarz"
    assert snapshot.quote.bid == 17.89
    assert snapshot.quote.ask == 17.98
    assert snapshot.quote.midpoint == pytest.approx(17.935)
    assert snapshot.quote.bid_size == 572
    assert snapshot.quote.change_percent == 2.31
    assert snapshot.quote.quoted_at == datetime(2026, 8, 12, 20, 44, 55, tzinfo=UTC)
    assert len(snapshot.trades) == 3
    assert snapshot.trades.index[0] == datetime(2026, 8, 12, 5, 30, 34, 611000, tzinfo=UTC)
    assert snapshot.trades.index[-1] == datetime(2026, 8, 12, 19, 59, 34, 234000, tzinfo=UTC)
    assert snapshot.trades["volume"].sum() == 215

    candles = market_day_candles(snapshot.trades, snapshot.quote)
    assert candles.index[0] == datetime(2026, 8, 12, 5, 30, tzinfo=UTC)
    assert candles.index[-1] == datetime(2026, 8, 12, 20, 44, tzinfo=UTC)
    assert candles["close"].iloc[-1] == pytest.approx(17.935)


def test_lang_schwarz_provider_uses_public_dwave_page():
    fetched_at = datetime(2026, 8, 12, 20, 45, tzinfo=UTC)

    def opener(request, timeout, context):
        assert request.full_url == "https://www.ls-tc.de/de/aktie/1875100"
        assert timeout == 12
        assert context is not None
        return FakeResponse()

    snapshot = LangSchwarzQuoteProvider(opener=opener, clock=lambda: fetched_at).snapshot(
        "us26740w1099"
    )

    assert snapshot.quote.isin == "US26740W1099"
    assert snapshot.quote.fetched_at == fetched_at
