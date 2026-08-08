"""Kostenlose reale Nachrichten aus der offiziellen yfinance-Suchschnittstelle."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import NewsItem, NewsProviderError

POSITIVE_HIGH = (
    "raises guidance",
    "fda approval",
    "wins contract",
    "major order",
    "share buyback",
    "beats estimates",
    "record revenue",
    "prognose angehoben",
    "großauftrag",
    "aktienrückkauf",
)
NEGATIVE_HIGH = (
    "cuts guidance",
    "profit warning",
    "misses estimates",
    "share offering",
    "data breach",
    "regulatory probe",
    "prognose gesenkt",
    "gewinnwarnung",
    "kapitalerhöhung",
)
POSITIVE_MEDIUM = (
    "upgrade",
    "partnership",
    "tops estimates",
    "revenue growth",
    "new product",
    "approval",
    "hochgestuft",
    "kooperation",
    "umsatzwachstum",
)
NEGATIVE_MEDIUM = (
    "downgrade",
    "lawsuit",
    "investigation",
    "recall",
    "supply constraints",
    "margin pressure",
    "herabgestuft",
    "klage",
    "ermittlung",
    "rückruf",
)
HIGH_CREDIBILITY_SOURCES = ("reuters", "associated press", "bloomberg", "financial times")
MEDIUM_HIGH_CREDIBILITY_SOURCES = ("yahoo finance", "cnbc", "wall street journal", "marketwatch")


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in phrases)


def classify_news_text(text: str) -> tuple[str, float]:
    """Bewertet nur explizite Ereigniswörter; gemischte Aussagen bleiben neutral."""

    normalized = " ".join(text.lower().split())
    positive_high = _contains(normalized, POSITIVE_HIGH)
    negative_high = _contains(normalized, NEGATIVE_HIGH)
    positive = positive_high or _contains(normalized, POSITIVE_MEDIUM)
    negative = negative_high or _contains(normalized, NEGATIVE_MEDIUM)
    if positive and negative:
        return "neutral", 0.4
    if positive:
        return "positiv", 0.75 if positive_high else 0.5
    if negative:
        return "negativ", 0.75 if negative_high else 0.5
    return "neutral", 0.2


def source_credibility(source: str) -> float:
    """Vorsichtige Quellenheuristik, keine journalistische Qualitätsgarantie."""

    normalized = source.lower()
    if any(value in normalized for value in HIGH_CREDIBILITY_SOURCES):
        return 0.9
    if any(value in normalized for value in MEDIUM_HIGH_CREDIBILITY_SOURCES):
        return 0.8
    return 0.6


def _published_at(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    raise NewsProviderError("Eine Meldung enthält keinen gültigen Veröffentlichungszeitpunkt.")


def _article_url(article: dict[str, Any]) -> str:
    direct = article.get("link")
    if isinstance(direct, str):
        return direct
    for key in ("canonicalUrl", "clickThroughUrl"):
        value = article.get(key)
        if isinstance(value, dict) and isinstance(value.get("url"), str):
            return value["url"]
    return ""


class YFinanceNewsProvider:
    name = "yfinance Nachrichten"
    is_demo = False

    def __init__(self, *, count_per_symbol: int = 8) -> None:
        self.count_per_symbol = min(max(count_per_symbol, 1), 20)

    def get_news(self, symbols: list[str]) -> list[NewsItem]:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - Installationsfehler
            raise NewsProviderError("yfinance ist nicht installiert.") from exc
        cache_path = Path("data/yfinance_cache")
        cache_path.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_path))
        requested = tuple(dict.fromkeys(symbol.upper().strip() for symbol in symbols if symbol.strip()))
        articles: dict[str, NewsItem] = {}
        errors: list[str] = []
        for symbol in requested:
            try:
                search = yf.Search(
                    symbol,
                    max_results=1,
                    news_count=self.count_per_symbol,
                    lists_count=0,
                    include_cb=False,
                    include_nav_links=False,
                    include_research=False,
                    timeout=15,
                    raise_errors=True,
                )
                for raw in search.news:
                    try:
                        item = self._normalize(raw, requested)
                    except NewsProviderError as exc:
                        errors.append(f"{symbol}: {exc}")
                        continue
                    if item is None:
                        continue
                    existing = articles.get(item.external_id)
                    if existing:
                        merged = tuple(dict.fromkeys(existing.related_symbols + item.related_symbols))
                        articles[item.external_id] = replace(existing, related_symbols=merged)
                    else:
                        articles[item.external_id] = item
            except Exception as exc:  # yfinance bündelt mehrere Netzwerk-Ausnahmetypen
                errors.append(f"{symbol}: {exc}")
        if not articles and errors:
            raise NewsProviderError("Nachrichten konnten nicht geladen werden: " + " | ".join(errors))
        return sorted(articles.values(), key=lambda item: item.published_at, reverse=True)

    @staticmethod
    def _normalize(raw: dict[str, Any], requested: tuple[str, ...]) -> NewsItem | None:
        article = raw.get("content") if isinstance(raw.get("content"), dict) else raw
        identifier = str(raw.get("uuid") or raw.get("id") or article.get("id") or "").strip()
        title = str(article.get("title") or "").strip()
        summary = str(article.get("summary") or article.get("description") or "").strip()
        if not title:
            raise NewsProviderError("Eine Meldung enthält keinen Titel.")
        url = _article_url(article)
        if not identifier:
            identifier = hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:32]
        provider = article.get("provider")
        source = str(
            article.get("publisher")
            or (provider.get("displayName") if isinstance(provider, dict) else "")
            or "Unbekannte Quelle"
        ).strip()
        published = _published_at(article.get("providerPublishTime") or article.get("pubDate"))
        raw_related = article.get("relatedTickers")
        related = (
            {str(value).upper() for value in raw_related if isinstance(value, str)}
            if isinstance(raw_related, list)
            else set()
        )
        related_symbols = tuple(symbol for symbol in requested if symbol in related)
        if not related_symbols:
            return None
        sentiment, impact = classify_news_text(f"{title} {summary}")
        age_hours = max((datetime.now(UTC) - published).total_seconds() / 3600, 0.0)
        return NewsItem(
            external_id=identifier,
            symbol=related_symbols[0],
            title=title,
            summary=summary,
            source=source,
            published_at=published,
            sentiment=sentiment,
            impact=impact,
            credibility=source_credibility(source),
            direct_relevance=True,
            possibly_priced_in=age_hours > 24,
            is_demo=False,
            url=url,
            related_symbols=related_symbols,
        )
