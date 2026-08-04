"""Explizit als Demo gekennzeichnete Nachrichten für Offline-Tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .base import NewsItem


class MockNewsProvider:
    name = "Demo-Nachrichten"
    is_demo = True

    def get_news(self, symbols: list[str]) -> list[NewsItem]:
        now = datetime.now(UTC)
        result: list[NewsItem] = []
        for index, symbol in enumerate(dict.fromkeys(value.upper() for value in symbols)):
            result.append(
                NewsItem(
                    external_id=f"demo-{symbol}-{now.date().isoformat()}",
                    symbol=symbol,
                    title=f"DEMO: Neutrale Beispielmeldung zu {symbol}",
                    summary="Diese Meldung ist erfunden und dient ausschließlich dem lokalen Funktionstest.",
                    source="Interner Demo-Anbieter",
                    published_at=now - timedelta(minutes=20 + index),
                    sentiment="neutral",
                    impact=0.2,
                    credibility=0.0,
                    direct_relevance=True,
                    possibly_priced_in=False,
                    is_demo=True,
                )
            )
        return result
