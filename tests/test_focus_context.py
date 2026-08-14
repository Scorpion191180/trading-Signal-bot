from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.focus.context import FocusContextProvider, score_market_prices
from src.news import NewsItem


def _market_prices(*, rising: bool) -> pd.DataFrame:
    direction = 1 if rising else -1
    rows = 20
    base = np.linspace(100, 100 + direction * 2, rows)
    return pd.DataFrame(
        {
            "QBTS": base,
            "IONQ": base * 1.01,
            "RGTI": base * 0.98,
            "QUBT": base * 1.02,
            "^IXIC": np.linspace(20_000, 20_000 + direction * 100, rows),
            "^GSPC": np.linspace(6_000, 6_000 + direction * 25, rows),
            "SOXX": np.linspace(300, 300 + direction * 3, rows),
            "^VIX": np.linspace(18, 18 - direction, rows),
            "GC=F": np.linspace(4_000, 4_000 - direction * 5, rows),
            "EURUSD=X": np.linspace(1.15, 1.15 - direction * 0.002, rows),
        }
    )


def test_market_context_follows_broad_confirmed_direction():
    positive, positive_reasons, available = score_market_prices(_market_prices(rising=True))
    negative, negative_reasons, _ = score_market_prices(_market_prices(rising=False))

    assert available is True
    assert positive > 52
    assert negative < 48
    assert any("D-Wave USA" in reason for reason in positive_reasons)
    assert any("Nasdaq" in reason for reason in negative_reasons)


def test_focus_context_combines_market_and_recent_news_without_dominating():
    now = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)
    item = NewsItem(
        external_id="qbts-news",
        symbol="QBTS",
        title="D-Wave wins major order",
        summary="",
        source="Reuters",
        published_at=now,
        sentiment="positiv",
        impact=0.75,
        credibility=0.9,
        direct_relevance=True,
        possibly_priced_in=False,
        is_demo=False,
        related_symbols=("QBTS",),
    )

    class NewsProvider:
        name = "Test"
        is_demo = False

        def get_news(self, _symbols: list[str]) -> list[NewsItem]:
            return [item]

    provider = FocusContextProvider(
        news_provider=NewsProvider(),
        market_loader=lambda: _market_prices(rising=True),
        clock=lambda: now,
    )
    context, items = provider.snapshot()

    assert context.available is True
    assert 58 < context.score <= 85
    assert context.news_score > 0.5
    assert context.headlines == (item.title,)
    assert items == (item,)
