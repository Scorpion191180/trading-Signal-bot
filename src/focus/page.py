"""Auf einen automatisch aktualisierten D-Wave-Tageschart reduzierte Seite."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src.data import ProviderError, YFinanceMarketDataProvider
from src.database import DataStore

from .analysis import DWAVE_INSTRUMENT, FocusPosition, analyze_timeframes, build_intraday_signal
from .charts import day_signal_chart
from .data import TimeframeBundle, load_dwave_timeframes
from .lang_schwarz import LangSchwarzQuoteProvider, LangSchwarzSnapshot
from .quote import (
    LiveQuote,
    TradegateQuoteProvider,
    market_day_candles,
    resample_intraday_candles,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_context_data() -> TimeframeBundle:
    return load_dwave_timeframes(YFinanceMarketDataProvider())


@st.cache_data(ttl=10, show_spinner=False)
def _cached_lang_schwarz_snapshot() -> LangSchwarzSnapshot:
    return LangSchwarzQuoteProvider().snapshot(DWAVE_INSTRUMENT.isin)


@st.cache_data(ttl=20, show_spinner=False)
def _cached_tradegate_day_trades() -> pd.DataFrame:
    return TradegateQuoteProvider().trades(DWAVE_INSTRUMENT.isin)


def _live_market_data() -> tuple[LiveQuote, pd.DataFrame, bool]:
    """Verwendet L&S primär und fällt nur bei einem echten Abruffehler auf Tradegate zurück."""

    try:
        snapshot = _cached_lang_schwarz_snapshot()
        return snapshot.quote, snapshot.trades, False
    except ProviderError as primary_error:
        try:
            fallback = TradegateQuoteProvider()
            return (
                fallback.quote(DWAVE_INSTRUMENT.isin),
                _cached_tradegate_day_trades(),
                True,
            )
        except ProviderError as fallback_error:
            raise ProviderError(
                f"Lang & Schwarz: {primary_error}; Tradegate: {fallback_error}"
            ) from fallback_error


def _stored_position(store: DataStore):
    return next(
        (position for position in store.list_real_positions() if position.symbol in {"RQ0", "RQ0.F"}),
        None,
    )


def _save_position(
    store: DataStore,
    *,
    invested: bool,
    average_price: float,
    quantity: float,
) -> None:
    for position in store.list_real_positions():
        if position.symbol in {"RQ0", "RQ0.F"}:
            store.delete_real_position(position.id)
    if invested:
        store.add_real_position(
            company=DWAVE_INSTRUMENT.name,
            symbol=DWAVE_INSTRUMENT.exchange_symbol,
            quantity=quantity,
            average_price=average_price,
            currency=DWAVE_INSTRUMENT.currency,
            isin_wkn=f"{DWAVE_INSTRUMENT.isin} / {DWAVE_INSTRUMENT.wkn}",
            reference_market="Lang & Schwarz",
            notes="Kurzfristige D-Wave-Beobachtung",
        )


def _position_control(store: DataStore) -> FocusPosition:
    stored = _stored_position(store)
    summary = "Position ändern" if stored else "Position eintragen"
    with st.expander(summary, expanded=False):
        invested = st.toggle("Ich bin investiert", value=stored is not None)
        c1, c2 = st.columns(2)
        average_price = c1.number_input(
            "Einstandskurs in EUR",
            min_value=0.001,
            value=float(stored.average_price if stored else 10.0),
            step=0.01,
            disabled=not invested,
        )
        quantity = c2.number_input(
            "Stückzahl",
            min_value=0.001,
            value=float(stored.quantity if stored else 1.0),
            step=1.0,
            disabled=not invested,
        )
        if st.button("Position speichern", width="stretch"):
            _save_position(
                store,
                invested=invested,
                average_price=average_price,
                quantity=quantity,
            )
            st.rerun()
    return FocusPosition(
        invested=invested,
        average_price=average_price if invested else None,
        quantity=quantity if invested else None,
    )


def _record_signal_event(action: str, price: float, timestamp: pd.Timestamp) -> list[dict[str, object]]:
    events = st.session_state.setdefault("dwave_signal_events", [])
    previous_action = st.session_state.get("dwave_previous_action")
    if action in {"BUY", "ADD", "SELL"} and previous_action != action:
        events.append({"action": action, "price": price, "timestamp": timestamp.isoformat()})
    st.session_state["dwave_previous_action"] = action
    trading_date = timestamp.tz_convert("Europe/Berlin").date()
    current_events = [
        event
        for event in events[-50:]
        if pd.Timestamp(event["timestamp"]).tz_convert("Europe/Berlin").date() == trading_date
    ]
    st.session_state["dwave_signal_events"] = current_events
    return current_events


@st.fragment(run_every=10)
def _automatic_day_chart(position: FocusPosition) -> None:
    try:
        quote, trades, fallback_active = _live_market_data()
        candles = market_day_candles(trades, quote)
    except ProviderError:
        st.error("Der Live-Tageschart ist gerade nicht erreichbar. Die App versucht es in zehn Sekunden erneut.")
        return

    bundle = _cached_context_data()
    frames = dict(bundle.frames)
    frames["1m"] = candles
    five_minutes = resample_intraday_candles(candles, 5)
    fifteen_minutes = resample_intraday_candles(candles, 15)
    if len(five_minutes) >= 35:
        frames["5m"] = five_minutes
    if len(fifteen_minutes) >= 35:
        frames["15m"] = fifteen_minutes

    analyses, enriched, _errors = analyze_timeframes(frames)
    signal = build_intraday_signal(
        analyses,
        enriched,
        position,
        now=datetime.now(UTC),
        live_price=quote.midpoint,
        session_close=time(22, 0) if fallback_active else time(23, 0),
    )
    events = _record_signal_event(signal.action, quote.midpoint, candles.index[-1])
    st.plotly_chart(
        day_signal_chart(candles, quote, signal, position, events),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
        key="dwave_live_day_chart",
    )
    quote_time = (quote.quoted_at or quote.fetched_at).astimezone(ZoneInfo("Europe/Berlin"))
    source = f"{quote.venue} · Ersatzquelle" if fallback_active else f"{quote.venue} · Hauptquelle"
    st.caption(
        f"{source} · Kurszeit {quote_time:%H:%M:%S} · automatisch alle 10 Sekunden · "
        "keine automatische Order"
    )


def focus_page(store: DataStore) -> None:
    st.title("D-Wave Quantum · Heute")
    st.caption("RQ0 · Lang & Schwarz · Tageschart mit automatischem Kurzfrist-Signal")
    position = _position_control(store)
    _automatic_day_chart(position)
