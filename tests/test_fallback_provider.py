from __future__ import annotations

import pandas as pd
import pytest

from src.data import (
    FallbackMarketDataProvider,
    MarketDataRequest,
    ProviderError,
    build_market_data_provider,
    source_name,
)


class StubProvider:
    is_demo = False

    def __init__(self, name: str, result: pd.DataFrame | Exception) -> None:
        self.name = name
        self.result = result

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result.copy()


def test_fallback_uses_next_real_provider_and_records_reason(market_frame):
    provider = FallbackMarketDataProvider(
        [
            StubProvider("Quelle A", ProviderError("Ausfall")),
            StubProvider("Quelle B", market_frame),
        ]
    )
    frame = provider.history(MarketDataRequest("TEST"))
    assert source_name(frame, provider) == "Quelle B"
    assert "Quelle A: Ausfall" in frame.attrs["fallback_reason"]


def test_fallback_reports_all_failures():
    provider = FallbackMarketDataProvider(
        [
            StubProvider("Quelle A", ProviderError("leer")),
            StubProvider("Quelle B", ProviderError("Rate-Limit")),
        ]
    )
    with pytest.raises(ProviderError, match="Quelle A: leer.*Quelle B: Rate-Limit"):
        provider.history(MarketDataRequest("TEST"))


def test_demo_provider_is_rejected_from_real_chain(market_frame):
    provider = StubProvider("Demo", market_frame)
    provider.is_demo = True
    with pytest.raises(ValueError, match="Demo-Anbieter"):
        FallbackMarketDataProvider([provider])


def test_factory_builds_configured_real_chain_without_secrets_in_name():
    provider = build_market_data_provider(
        "auto",
        twelve_data_api_key="twelve-secret",
        alpaca_api_key_id="alpaca-id",
        alpaca_api_secret_key="alpaca-secret",
    )
    assert provider.name == "yfinance → Alpaca (IEX) → Twelve Data"
    assert provider.is_demo is False
    assert "secret" not in provider.name
