"""Austauschbare Nachrichtenschicht; im MVP eindeutig gekennzeichnete Demo-Daten."""

from .base import NewsItem, NewsProvider
from .mock_provider import MockNewsProvider

__all__ = ["MockNewsProvider", "NewsItem", "NewsProvider"]
