"""Reduzierte Streamlit-App für kurzfristige D-Wave-Signale."""

from __future__ import annotations

import logging

import streamlit as st

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory
from src.focus.page import focus_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
SERVICE_SCHEMA_VERSION = "1.1-background-paper-bot"
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
    [data-testid="stHeader"] {background: rgba(18,25,28,.92); height: .4rem;}
    [data-testid="stToolbar"] {display: none;}
    .block-container {padding: .08rem .55rem .25rem; max-width: none;}
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
    .paper-account-bar {
      display: flex; align-items: center; gap: .65rem; flex-wrap: wrap; margin: .02rem 0 .12rem;
      padding: .22rem .48rem; border: 1px solid #334147; border-radius: .28rem;
      background: #10181b; color: #c3cdd1; font-size: .64rem;
    }
    .paper-account-bar b {color: #f1f5f6; letter-spacing: .025em;}
    .paper-account-bar span {padding-left: .65rem; border-left: 1px solid #344147;}
    .paper-account-bar small {margin-left: auto; color: #77878d; font-size: .59rem;}
    .bot-console {
      display: grid; grid-template-columns: repeat(8, max-content); align-items: center;
      gap: .34rem .75rem; margin: .05rem 0 .12rem; padding: .3rem .5rem;
      border: 1px solid #334147; border-radius: .3rem; background: #10181b;
      color: #d8e0e3; font-size: .68rem; overflow-x: auto; scrollbar-width: none;
    }
    .bot-console span {white-space: nowrap;}
    .bot-console small {color: #75858b; font-size: .52rem; letter-spacing: .055em; margin-right: .18rem;}
    .bot-console b {color: #eef3f4; font-weight: 680;}
    .bot-service {font-weight: 750; letter-spacing: .035em;}
    .st-key-bot_controls {margin-bottom: .1rem;}
    .st-key-bot_controls button, .st-key-bot_controls [data-testid="stPopoverButton"] {
      min-height: 2rem !important; height: 2rem !important; padding: .12rem .45rem !important;
      font-size: .69rem !important;
    }
    .st-key-bot_controls button p, .st-key-bot_controls [data-testid="stPopoverButton"] p {
      font-size: .69rem !important;
    }
    .st-key-chart_toolbar {margin: 0 0 .08rem;}
    .trend-forecast-bar {
      display: flex; align-items: center; gap: .75rem; padding: .3rem .55rem; margin: .2rem 0;
      border: 1px solid #2d3a3f; border-radius: .4rem; background: #11191d; font-size: .68rem;
    }
    .trend-forecast-bar label {color: #829198; font-size: .58rem; letter-spacing: .06em; white-space: nowrap;}
    .trend-forecast-cell {display: inline-flex; align-items: baseline; gap: .28rem; padding-left: .65rem; border-left: 1px solid #344147;}
    .trend-forecast-cell b, .trend-forecast-cell strong {color: #e5eaec; white-space: nowrap;}
    .trend-forecast-cell em {font-style: normal; font-weight: 700; white-space: nowrap;}
    .trend-forecast-cell small {color: #78878d; white-space: nowrap;}
    .trend-forecast-bar i {margin-left: auto; color: #69777d; font-size: .56rem; white-space: nowrap;}
    .replay-summary-bar {
      display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; margin: .12rem 0;
      padding: .24rem .5rem; border: 1px solid #334147; border-radius: .3rem;
      background: #10181b; color: #aebbc0; font-size: .64rem;
    }
    .replay-summary-bar label {color: #829198; font-size: .58rem; letter-spacing: .06em;}
    .replay-summary-bar b, .replay-summary-bar strong {color: #eef2f3;}
    .replay-summary-bar span {padding-left: .65rem; border-left: 1px solid #344147;}
    .replay-summary-bar small {margin-left: auto; color: #77878d; font-size: .58rem;}
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
      [data-testid="stHeader"] {height: 0; min-height: 0;}
      .block-container {padding: .08rem .18rem .12rem;}
      .market-strip {margin-left: -.18rem; margin-right: -.18rem;}
      .instrument-header {gap: .7rem; flex-wrap: wrap;}
      .instrument-name {font-size: .95rem;}
      .live-price {font-size: .9rem;}
      .bot-console {
        grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .22rem .45rem;
        padding: .28rem .38rem; font-size: .64rem; overflow: hidden;
      }
      .bot-console span {min-width: 0; overflow: hidden; text-overflow: ellipsis;}
      .bot-console small {display: block; margin: 0 0 .02rem; font-size: .47rem;}
      .bot-service, .bot-signal {grid-column: span 1;}
      .st-key-bot_controls [data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
        gap: .28rem !important;
      }
      .st-key-bot_controls [data-testid="stColumn"] {
        flex: 1 1 50% !important; width: 50% !important; min-width: 0 !important;
      }
      .st-key-chart_toolbar [data-testid="stHorizontalBlock"] {
        display: grid !important; grid-template-columns: minmax(0, 1fr) 5.7rem 2.6rem !important;
        gap: .22rem !important;
      }
      .st-key-chart_toolbar [data-testid="stColumn"] {
        width: auto !important; min-width: 0 !important;
      }
      .st-key-chart_toolbar [data-testid="stButtonGroup"] {
        overflow-x: auto !important; scrollbar-width: none; justify-content: flex-start !important;
      }
      .st-key-chart_toolbar [data-testid="stButtonGroup"] > div {flex-wrap: nowrap !important;}
      [data-testid="stPlotlyChart"] {margin-top: -.08rem;}
      .paper-account-bar small {margin-left: 0; width: 100%;}
      .trend-forecast-bar {flex-wrap: wrap; gap: .4rem;}
      .trend-forecast-bar i {margin-left: 0;}
      .replay-summary-bar small {margin-left: 0; width: 100%;}
      div[data-testid="stHorizontalBlock"] {gap: .28rem;}
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
