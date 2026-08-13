"""Auf einen automatisch aktualisierten D-Wave-Tageschart reduzierte Seite."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src.data import ProviderError, YFinanceMarketDataProvider
from src.database import DataStore

from .analysis import DWAVE_INSTRUMENT, FocusPosition, IntradaySignal, analyze_timeframes, build_intraday_signal
from .charts import CANDLE_INTERVAL_LABELS, day_signal_chart
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


def _update_forward_validation(
    store: DataStore,
    candles: pd.DataFrame,
    quote: LiveQuote,
    signal: IntradaySignal,
) -> dict[str, float | int | None]:
    observations = [
        (pd.Timestamp(timestamp).to_pydatetime(), float(price))
        for timestamp, price in candles["close"].items()
    ]
    store.evaluate_focus_forecasts(
        DWAVE_INSTRUMENT.exchange_symbol,
        observations,
        provider=quote.venue,
    )
    if (
        signal.market_open
        and signal.data_age_minutes <= 4
        and signal.forecast_low is not None
        and signal.forecast_high is not None
    ):
        store.record_focus_forecast(
            symbol=DWAVE_INSTRUMENT.exchange_symbol,
            provider=quote.venue,
            forecast_at=quote.quoted_at or quote.fetched_at,
            entry_price=quote.midpoint,
            bid=quote.bid,
            ask=quote.ask,
            direction=signal.forecast_direction,
            model_score=signal.score,
            forecast_low=signal.forecast_low,
            forecast_high=signal.forecast_high,
            market_regime=signal.market_regime,
            strategy_votes=signal.strategy_votes,
            spread_percent=signal.spread_percent or 0.0,
        )
    return store.focus_forecast_metrics(
        symbol=DWAVE_INSTRUMENT.exchange_symbol,
        horizon_minutes=15,
    )


def _validation_text(metrics: dict[str, float | int | None]) -> str:
    recorded = int(metrics["recorded"] or 0)
    completed = int(metrics["completed"] or 0)
    if completed < 20:
        forecast_label = "Prognose" if recorded == 1 else "Prognosen"
        return (
            f"Vorwärtsprüfung · {recorded} {forecast_label} gespeichert · "
            f"{completed} nach 15 Minuten ausgewertet · "
            f"aussagekräftiger ab 20 abgeschlossenen Fällen"
        )
    return (
        f"Vorwärtsprüfung · {completed} echte 15-Minuten-Fälle · "
        f"Richtungstreffer {float(metrics['direction_accuracy']):.1f} % · "
        f"Kurs in Zone {float(metrics['zone_coverage']):.1f} % · "
        "nur später eingetroffene Kurse"
    )


@st.fragment(run_every=10)
def _automatic_day_chart(store: DataStore, position: FocusPosition, candle_minutes: int) -> None:
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
        spread_percent=(quote.ask - quote.bid) / quote.midpoint * 100,
        order_imbalance=(quote.bid_size - quote.ask_size) / (quote.bid_size + quote.ask_size)
        if quote.bid_size is not None
        and quote.ask_size is not None
        and quote.bid_size + quote.ask_size > 0
        else None,
    )
    events = _record_signal_event(signal.action, quote.midpoint, candles.index[-1])
    validation = _update_forward_validation(store, candles, quote, signal)
    st.plotly_chart(
        day_signal_chart(candles, quote, signal, position, events, candle_minutes),
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
    st.caption(_validation_text(validation))


def focus_page(store: DataStore) -> None:
    st.title("D-Wave Quantum · Heute")
    st.caption("RQ0 · Lang & Schwarz · Tageschart mit automatischem Kurzfrist-Signal")
    candle_minutes = st.selectbox(
        "Kerzenintervall",
        options=list(CANDLE_INTERVAL_LABELS),
        index=1,
        format_func=CANDLE_INTERVAL_LABELS.get,
        key="dwave_candle_interval",
    )
    position = _position_control(store)
    _automatic_day_chart(store, position, int(candle_minutes))
