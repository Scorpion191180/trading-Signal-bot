"""Austauschbare Kursdatenanbieter."""

from .alpaca_provider import AlpacaMarketDataProvider
from .base import MarketDataProvider, MarketDataRequest, ProviderError, recommended_period, source_name
from .fallback_provider import FallbackMarketDataProvider
from .mock_provider import MockMarketDataProvider
from .twelve_data_provider import TwelveDataMarketDataProvider
from .yfinance_provider import YFinanceMarketDataProvider


def build_market_data_provider(
    data_provider: str,
    twelve_data_api_key: str = "",
    alpaca_api_key_id: str = "",
    alpaca_api_secret_key: str = "",
) -> MarketDataProvider:
    """Erzeugt Testmodus oder eine priorisierte Kette ausschließlich realer Datenquellen."""

    selected = data_provider.lower().strip()
    if selected == "mock":
        return MockMarketDataProvider()
    if selected not in {"auto", "yfinance"}:
        raise ValueError(f"Unbekannter DATA_PROVIDER: {data_provider}")
    providers: list[MarketDataProvider] = [YFinanceMarketDataProvider()]
    if alpaca_api_key_id.strip() and alpaca_api_secret_key.strip():
        providers.append(AlpacaMarketDataProvider(alpaca_api_key_id, alpaca_api_secret_key))
    if twelve_data_api_key.strip():
        providers.append(TwelveDataMarketDataProvider(twelve_data_api_key))
    return FallbackMarketDataProvider(providers)

__all__ = [
    "AlpacaMarketDataProvider",
    "FallbackMarketDataProvider",
    "MarketDataProvider",
    "MarketDataRequest",
    "MockMarketDataProvider",
    "ProviderError",
    "recommended_period",
    "TwelveDataMarketDataProvider",
    "YFinanceMarketDataProvider",
    "build_market_data_provider",
    "source_name",
]
