"""Vertrag für strukturierte Nachrichtenanbieter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class NewsItem:
    external_id: str
    symbol: str
    title: str
    summary: str
    source: str
    published_at: datetime
    sentiment: str
    impact: float
    credibility: float
    direct_relevance: bool
    possibly_priced_in: bool
    is_demo: bool


class NewsProvider(Protocol):
    name: str
    is_demo: bool

    def get_news(self, symbols: list[str]) -> list[NewsItem]:
        """Liefert deduplizierte, strukturierte Nachrichten."""


def news_score(items: list[NewsItem]) -> float:
    """Aggregiert Nachrichten zu einem neutral zentrierten Faktor von 0 bis 1."""

    if not items:
        return 0.5
    values: list[float] = []
    for item in items:
        direction = {"positiv": 1.0, "negativ": -1.0}.get(item.sentiment.lower(), 0.0)
        priced_discount = 0.5 if item.possibly_priced_in else 1.0
        relevance = 1.0 if item.direct_relevance else 0.5
        values.append(direction * item.impact * item.credibility * priced_discount * relevance)
    return min(max(0.5 + sum(values) / max(len(values), 1) / 2, 0.0), 1.0)
