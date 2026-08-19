"""Austauschbare Schicht für echte Nachrichten und klar getrennte Offline-Testdaten."""

from .base import NewsItem, NewsProvider, NewsProviderError, news_score
from .mock_provider import MockNewsProvider
from .yfinance_provider import YFinanceNewsProvider, classify_news_text

__all__ = [
    "MockNewsProvider",
    "NewsItem",
    "NewsProvider",
    "NewsProviderError",
    "YFinanceNewsProvider",
    "classify_news_text",
    "news_score",
]
