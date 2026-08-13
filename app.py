"""Reduzierte Streamlit-App für kurzfristige D-Wave-Signale."""

from __future__ import annotations

import logging

import streamlit as st

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory
from src.focus.page import focus_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
SERVICE_SCHEMA_VERSION = "0.9-stock3-ls-bid-chart"
st.set_page_config(
    page_title="D-Wave Kurzfrist-Signal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
    :root {color-scheme: dark;}
    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {background: #12191c;}
    [data-testid="stHeader"] {background: rgba(18,25,28,.92); height: 2.2rem;}
    .block-container {padding: .15rem .8rem 1.2rem; max-width: none;}
    [data-testid="stSidebar"] {display: none;}
    .market-strip {
      display: flex; align-items: center; gap: 0; overflow-x: auto; white-space: nowrap;
      margin: 0 -.8rem .25rem; border-bottom: 1px solid #2b3539; border-top: 1px solid #2b3539;
      background: #0d1315; min-height: 25px; scrollbar-width: none;
    }
    .market-cell {font-size: .68rem; padding: .24rem .58rem; border-right: 1px solid #2b3539; color: #d6dde0;}
    .market-cell em {font-style: normal; margin-left: .15rem;}
    .market-unavailable {color: #66767d;}
    .instrument-header {display: flex; align-items: center; gap: clamp(1rem, 4vw, 3.5rem); min-height: 3rem;}
    .instrument-name {font-size: 1.12rem; font-weight: 650; color: #f3f6f7; padding: .38rem 0; white-space: nowrap;}
    .instrument-name span, .venue-name span {color: #9aa8ad; font-size: .8rem;}
    .venue-name {font-size: .9rem; color: #e1e7e9; padding-top: .25rem;}
    .venue-name small {display: block; color: #728087; font-size: .58rem; margin-top: -.05rem;}
    .live-price {font-size: 1.08rem; font-weight: 700; color: #f3f6f7; padding-top: .2rem; white-space: nowrap;}
    .live-price span {font-size: .88rem; margin-left: .2rem;}
    .live-price small {display: block; color: #728087; font-size: .62rem; font-weight: 500;}
    [data-testid="stPlotlyChart"] {border-top: 1px solid #2a3438; border-bottom: 1px solid #2a3438;}
    .chart-selection-summary {
      display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; margin: .08rem 0 .1rem;
      padding: .18rem .45rem; border: 1px solid #2b3539; background: #0f1619; color: #9eacb1;
      font-size: .62rem; border-radius: .25rem; min-height: 1.25rem;
    }
    .chart-selection-summary b {color: #f1f5f6;}
    .chart-selection-summary span {padding-left: .7rem; border-left: 1px solid #334046;}
    [data-testid="stButtonGroup"] button {
      min-height: 1.5rem !important; height: 1.5rem !important; border-radius: .28rem !important;
      padding: .05rem .32rem !important; font-size: .61rem !important; white-space: nowrap !important;
    }
    [data-testid="stButtonGroup"] button p {
      font-size: .61rem !important; line-height: 1 !important; white-space: nowrap !important;
    }
    [data-testid="stSelectbox"], [data-testid="stSelectbox"] .react-aria-ComboBox,
    [data-testid="stSelectbox"] .react-aria-ComboBox > div, [data-testid="stSelectbox"] input {
      min-height: 1.55rem !important; height: 1.55rem !important; font-size: .62rem !important;
    }
    [data-testid="stSelectbox"] svg {width: .7rem; height: .7rem;}
    [data-testid="stPopoverButton"] {
      min-height: 1.55rem !important; height: 1.55rem !important; padding: .05rem .25rem !important;
      border-color: #344147; font-size: .61rem !important; white-space: nowrap !important;
    }
    [data-testid="stPopoverButton"] p {font-size: .61rem !important; white-space: nowrap !important;}
    [data-testid="stCaptionContainer"] {color: #77868c; font-size: .68rem;}
    .modebar {top: 6px !important; right: 4px !important;}
    .modebar-btn path {fill: #a7b3b8 !important;}
    @media (max-width: 760px) {
      .block-container {padding-left: .35rem; padding-right: .35rem;}
      .market-strip {margin-left: -.35rem; margin-right: -.35rem;}
      .instrument-header {gap: .7rem; flex-wrap: wrap;}
      .instrument-name {font-size: .95rem;}
      .live-price {font-size: .9rem;}
      div[data-testid="stHorizontalBlock"] {gap: .4rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def services(schema_version: str = SERVICE_SCHEMA_VERSION) -> DataStore:
    """Erzeugt den Dienst bei Datenbankschema-Wechseln bewusst neu."""

    _ = schema_version
    settings = AppSettings.from_env()
    engine = create_database(settings.database_url)
    store = DataStore(create_session_factory(engine), settings)
    return store


focus_page(services(SERVICE_SCHEMA_VERSION))
