"""Reduzierte Streamlit-App für kurzfristige D-Wave-Signale."""

from __future__ import annotations

import logging

import streamlit as st

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory
from src.focus.page import focus_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
st.set_page_config(
    page_title="D-Wave Kurzfrist-Signal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1050px;}
    div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.24); padding: .7rem; border-radius: .8rem;}
    [data-testid="stSidebar"] {display: none;}
    @media (max-width: 640px) {
      .block-container {padding-left: .7rem; padding-right: .7rem;}
      h1 {font-size: 1.62rem !important;}
      h2 {font-size: 1.22rem !important;}
      div[data-testid="stHorizontalBlock"] {gap: .4rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def services() -> DataStore:
    settings = AppSettings.from_env()
    engine = create_database(settings.database_url)
    store = DataStore(create_session_factory(engine), settings)
    return store


focus_page(services())
