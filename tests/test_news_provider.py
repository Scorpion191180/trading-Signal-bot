from __future__ import annotations

from datetime import UTC, datetime, timedelta

import yfinance as yf

from src.news import NewsItem, YFinanceNewsProvider, classify_news_text, news_score


def _item(
    external_id: str = "news-1",
    *,
    symbol: str = "AAPL",
    sentiment: str = "positiv",
    published_at: datetime | None = None,
    related_symbols: tuple[str, ...] = ("AAPL",),
) -> NewsItem:
    return NewsItem(
        external_id=external_id,
        symbol=symbol,
        title="Testmeldung",
        summary="",
        source="Reuters",
        published_at=published_at or datetime.now(UTC),
        sentiment=sentiment,
        impact=0.6,
        credibility=0.9,
        direct_relevance=True,
        possibly_priced_in=False,
        is_demo=False,
        url="https://example.com/news",
        related_symbols=related_symbols,
    )


def test_headline_classification_is_conservative_for_mixed_news():
    assert classify_news_text("Company raises guidance after record revenue") == ("positiv", 0.75)
    assert classify_news_text("Company cuts guidance after profit warning") == ("negativ", 0.75)
    sentiment, impact = classify_news_text(
        "Revenue growth beats estimates but supply constraints create margin pressure"
    )
    assert sentiment == "neutral"
    assert impact == 0.4
    assert classify_news_text("CEO speaks at an industry conference") == ("neutral", 0.2)


def test_news_score_discounts_old_items():
    now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    fresh = _item(published_at=now - timedelta(hours=2))
    old = _item(published_at=now - timedelta(hours=100))
    assert news_score([fresh], now=now) > news_score([old], now=now) > 0.5


def test_yfinance_provider_deduplicates_and_keeps_related_watchlist_symbols(monkeypatch):
    article = {
        "uuid": "article-1",
        "title": "Apple wins contract in new partnership",
        "publisher": "Reuters",
        "link": "https://example.com/article-1",
        "providerPublishTime": int(datetime.now(UTC).timestamp()),
        "relatedTickers": ["AAPL", "MSFT", "OTHER"],
    }

    class FakeSearch:
        def __init__(self, *_args, **_kwargs) -> None:
            self.news = [article]

    monkeypatch.setattr(yf, "Search", FakeSearch)
    items = YFinanceNewsProvider(count_per_symbol=3).get_news(["AAPL", "MSFT"])

    assert len(items) == 1
    assert items[0].external_id == "article-1"
    assert items[0].related_symbols == ("AAPL", "MSFT")
    assert items[0].sentiment == "positiv"
    assert items[0].source == "Reuters"


def test_news_upsert_is_idempotent_and_merges_symbol_relation(store):
    first = _item(related_symbols=("AAPL",))
    second = _item(symbol="MSFT", related_symbols=("MSFT",))

    assert store.upsert_news([first]) == 1
    assert store.upsert_news([second]) == 0
    assert len(store.list_news(symbol="AAPL")) == 1
    assert len(store.list_news(symbol="MSFT")) == 1
    assert store.list_news()[0].related_symbols == "AAPL,MSFT"
