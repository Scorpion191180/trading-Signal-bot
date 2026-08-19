"""CLI-Einstieg für Render Cron, Background Worker oder GitHub Actions."""

from __future__ import annotations

import logging

from src.config import AppSettings
from src.data import build_market_data_provider
from src.database import DataStore, create_database, create_session_factory
from src.news import YFinanceNewsProvider

from .service import TradingAgent


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = AppSettings.from_env()
    engine = create_database(settings.database_url)
    store = DataStore(create_session_factory(engine), settings)
    store.seed_defaults()
    provider = build_market_data_provider(
        settings.data_provider,
        settings.twelve_data_api_key,
        settings.alpaca_api_key_id,
        settings.alpaca_api_secret_key,
    )
    news_provider = None if provider.is_demo else YFinanceNewsProvider()
    result = TradingAgent(provider, store, settings, news_provider).run()
    if result.skipped_duplicate:
        logging.info("Der aktuelle 30-Minuten-Lauf wurde bereits verarbeitet.")
        return 0
    logging.info("Agentenlauf: %s Signale, %s virtuelle Aktionen", result.signals, result.virtual_actions)
    for error in result.errors:
        logging.error(error)
    return 1 if result.errors and result.signals == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
