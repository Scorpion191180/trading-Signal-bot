"""Streamlit-Einstiegspunkt des Trading-Signal-Agenten."""

from __future__ import annotations

import logging

import streamlit as st

from src.agent import TradingAgent
from src.config import AppSettings
from src.data import build_market_data_provider
from src.database import DataStore, create_database, create_session_factory
from src.ui import pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
st.set_page_config(page_title="Trading-Signal-Agent", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem; max-width: 1100px;}
    div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.25); padding: .7rem; border-radius: .7rem;}
    @media (max-width: 640px) {
      .block-container {padding-left: .65rem; padding-right: .65rem;}
      h1 {font-size: 1.65rem !important;}
      h2 {font-size: 1.25rem !important;}
      div[data-testid="stHorizontalBlock"] {gap: .4rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def services() -> tuple[AppSettings, DataStore]:
    settings = AppSettings.from_env()
    engine = create_database(settings.database_url)
    store = DataStore(create_session_factory(engine), settings)
    store.seed_defaults()
    return settings, store


settings, store = services()
provider = build_market_data_provider(
    settings.data_provider,
    settings.twelve_data_api_key,
    settings.alpaca_api_key_id,
    settings.alpaca_api_secret_key,
)
agent = TradingAgent(provider, store, settings)

navigation = [
    "Übersicht",
    "Echtes Depot",
    "Watchlist",
    "Agenten-Depot",
    "Aktienanalyse",
    "Markt-Scanner",
    "Nachrichten",
    "Strategien",
    "Backtesting",
    "Trade-Journal",
    "Einstellungen",
    "Systemstatus",
]
page = st.sidebar.radio("Navigation", navigation)
if provider.is_demo:
    st.sidebar.warning("Offline-Testmodus durch DATA_PROVIDER=mock aktiviert")
else:
    st.sidebar.caption(f"Reale Kursquellen: {provider.name}")
st.sidebar.caption("Keine echten Orders · keine Trade-Republic-Verbindung · keine Anlageberatung")

if page == "Übersicht":
    pages.overview(store, provider)
elif page == "Echtes Depot":
    pages.real_portfolio(store)
elif page == "Watchlist":
    pages.watchlist(store)
elif page == "Agenten-Depot":
    pages.agent_portfolio(store, agent)
elif page == "Aktienanalyse":
    pages.analysis_page(store, provider, settings)
elif page == "Markt-Scanner":
    pages.scanner(store, provider, settings)
elif page == "Nachrichten":
    pages.news_page(store)
elif page == "Strategien":
    pages.strategies_page()
elif page == "Backtesting":
    pages.backtesting_page(store, provider)
elif page == "Trade-Journal":
    pages.trade_journal(store)
elif page == "Einstellungen":
    pages.settings_page(settings, provider)
elif page == "Systemstatus":
    pages.system_status(store, provider, settings)
