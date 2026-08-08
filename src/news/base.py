"""Vertrag für strukturierte Nachrichtenanbieter."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class NewsProviderError(RuntimeError):
    """Verständlich behandelbarer Fehler einer externen Nachrichtenquelle."""


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
    url: str = ""
    related_symbols: tuple[str, ...] = ()


class NewsProvider(Protocol):
    name: str
    is_demo: bool

    def get_news(self, symbols: list[str]) -> list[NewsItem]:
        """Liefert deduplizierte, strukturierte Nachrichten."""


def news_score(items: Sequence[NewsItem], *, now: datetime | None = None) -> float:
    """Aggregiert Nachrichten zu einem neutral zentrierten Faktor von 0 bis 1."""

    if not items:
        return 0.5
    current = now or datetime.now(UTC)
    values: list[float] = []
    for item in items:
        direction = {"positiv": 1.0, "negativ": -1.0}.get(item.sentiment.lower(), 0.0)
        priced_discount = 0.5 if item.possibly_priced_in else 1.0
        relevance = 1.0 if item.direct_relevance else 0.5
        published = item.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_hours = max((current - published).total_seconds() / 3600, 0.0)
        age_discount = 1.0 if age_hours <= 24 else 0.5 if age_hours <= 72 else 0.2
        values.append(
            direction * item.impact * item.credibility * priced_discount * relevance * age_discount
        )
    return min(max(0.5 + sum(values) / max(len(values), 1) / 2, 0.0), 1.0)
