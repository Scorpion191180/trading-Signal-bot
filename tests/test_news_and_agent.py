from __future__ import annotations

from src.agent import TradingAgent
from src.config import AppSettings
from src.data import MockMarketDataProvider
from src.news.base import NewsProviderError, news_score
from src.news.mock_provider import MockNewsProvider


def test_mock_news_is_neutral_and_clearly_marked():
    items = MockNewsProvider().get_news(["AAPL"])
    assert len(items) == 1
    assert items[0].is_demo
    assert items[0].credibility == 0
    assert news_score(items) == 0.5


def test_agent_prevents_duplicate_run(store):
    settings = AppSettings(database_url="sqlite:///:memory:", data_provider="mock")
    agent = TradingAgent(MockMarketDataProvider(), store, settings)
    first = agent.run()
    second = agent.run()
    assert first.run_id is not None
    assert first.signals == 27
    assert second.skipped_duplicate is True
    assert len(store.list_signals()) == 27


def test_agent_keeps_news_neutral_when_provider_fails(store):
    class FailingNewsProvider:
        name = "Ausgefallene Testquelle"
        is_demo = False

        def get_news(self, symbols):
            raise NewsProviderError("Rate-Limit")

    settings = AppSettings(database_url="sqlite:///:memory:", data_provider="mock")
    agent = TradingAgent(MockMarketDataProvider(), store, settings, FailingNewsProvider())
    result = agent.run(force=True)

    assert result.signals == 27
    assert result.errors == ()
    assert store.list_news() == []
    assert {signal.news_factor for signal in store.list_signals()} == {0.5}
