"""Auf einen automatisch aktualisierten D-Wave-Tageschart reduzierte Seite."""

from __future__ import annotations

import warnings
from dataclasses import asdict
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src.data import ProviderError, YFinanceMarketDataProvider
from src.database import DataStore

from .analysis import DWAVE_INSTRUMENT, FocusPosition, IntradaySignal, analyze_timeframes, build_intraday_signal
from .charts import day_signal_chart
from .data import TimeframeBundle, load_dwave_timeframes
from .display import (
    DEFAULT_INTERVAL,
    DISPLAY_INTERVAL_LABELS,
    PERIOD_INTERVALS,
    PERIOD_OPTIONS,
    select_display_candles,
)
from .lang_schwarz import LangSchwarzQuoteProvider
from .quote import (
    LiveQuote,
    TradegateQuoteProvider,
    market_day_candles,
    resample_intraday_candles,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_context_data() -> tuple[dict[str, pd.DataFrame], dict[str, str], str, str, str]:
    """Cached nur serialisierbare Werte, damit ein Code-Reload keine alten Klassentypen festhält."""

    bundle = load_dwave_timeframes(YFinanceMarketDataProvider())
    return bundle.frames, bundle.errors, bundle.provider, bundle.symbol, bundle.venue


@st.cache_data(ttl=10, show_spinner=False)
def _cached_lang_schwarz_snapshot() -> tuple[dict[str, object], pd.DataFrame]:
    """Vermeidet Dataclass-Objekte im Streamlit-Cache über Code-Reloads hinweg."""

    snapshot = LangSchwarzQuoteProvider().snapshot(DWAVE_INSTRUMENT.isin)
    return asdict(snapshot.quote), snapshot.trades


@st.cache_data(ttl=20, show_spinner=False)
def _cached_tradegate_day_trades() -> pd.DataFrame:
    return TradegateQuoteProvider().trades(DWAVE_INSTRUMENT.isin)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_market_strip() -> list[tuple[str, float, float]]:
    """Lädt den kompakten Marktüberblick des Fotovorbilds; bei Ausfall bleibt er einfach leer."""

    instruments = {
        "DAX": "^GDAXI",
        "Euro Stoxx 50": "^STOXX50E",
        "US 500": "^GSPC",
        "US Tech 100": "^NDX",
        "Gold": "GC=F",
        "EUR/USD": "EURUSD=X",
    }
    try:
        import yfinance as yf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(
                list(instruments.values()),
                period="5d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=12,
            )
        items: list[tuple[str, float, float]] = []
        closes = data["Close"]
        for label, symbol in instruments.items():
            series = pd.to_numeric(closes[symbol], errors="coerce").dropna()
            if len(series) < 2:
                continue
            latest = float(series.iloc[-1])
            change = (latest / float(series.iloc[-2]) - 1) * 100
            items.append((label, latest, change))
        return items
    except Exception:
        return []


def _live_market_data() -> tuple[LiveQuote, pd.DataFrame, bool]:
    """Verwendet L&S primär und fällt nur bei einem echten Abruffehler auf Tradegate zurück."""

    try:
        quote_data, trades = _cached_lang_schwarz_snapshot()
        return LiveQuote(**quote_data), trades, False
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
    summary = "Position" if stored else "Position eintragen"
    with st.popover(summary, icon=":material/account_balance_wallet:", width="stretch"):
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


def _render_market_strip() -> None:
    items = _cached_market_strip()
    cells = []
    if items:
        for label, value, change in items:
            color = "#58c981" if change >= 0 else "#e06469"
            cells.append(
                f'<span class="market-cell"><b>{label}</b> {value:,.2f} '
                f'<em style="color:{color}">{change:+.2f} %</em></span>'
            )
    else:
        for label in ("DAX", "Euro Stoxx 50", "US 500", "US Tech 100", "Gold", "EUR/USD"):
            cells.append(f'<span class="market-cell market-unavailable"><b>{label}</b> —</span>')
    st.markdown(f'<div class="market-strip">{"".join(cells)}</div>', unsafe_allow_html=True)


def _render_instrument_header(store: DataStore, quote: LiveQuote, fallback_active: bool) -> FocusPosition:
    change = quote.change_percent or 0.0
    change_color = "#58c981" if change >= 0 else "#e06469"
    source_badge = "Ersatzquelle" if fallback_active else "Hauptquelle"
    header_column, position_column = st.columns([8.1, 1.9], vertical_alignment="center")
    header_column.markdown(
        '<div class="instrument-header">'
        '<div class="instrument-name">D-Wave Quantum <span>⌄</span></div>'
        f'<div class="venue-name">{quote.venue} <span>⌄</span><small>{source_badge}</small></div>'
        f'<div class="live-price">{quote.midpoint:.3f} € '
        f'<span style="color:{change_color}">{change:+.2f} %</span>'
        f'<small>Geld {quote.bid:.3f} · Brief {quote.ask:.3f}</small></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    with position_column:
        position = _position_control(store)
        st.caption(_position_summary(position, quote))
    return position


def _position_summary(position: FocusPosition, quote: LiveQuote) -> str:
    if not position.invested or not position.average_price or not position.quantity:
        return "Keine Position"
    pnl = (quote.bid - position.average_price) * position.quantity
    return f"{position.quantity:g} Stück · {pnl:+.2f} €"


def _signal_mode_text(position: FocusPosition, quote: LiveQuote) -> str:
    """Erklärt knapp, warum ein Kauf- oder Nachkaufsignal möglich ist."""

    if not position.invested:
        return "Signalmodus · nicht investiert: Eine bestätigte Einstiegslage erscheint als KAUFEN."
    if position.average_price is not None and quote.midpoint < position.average_price:
        distance = (quote.midpoint / position.average_price - 1) * 100
        return (
            "Signalmodus · Position aktiv: Eine bestätigte Einstiegslage heißt NACHKAUFEN. "
            f"Aktuell {distance:.1f} % unter deinem Einstand – deshalb verhindert die Risikoregel ein Verbilligen."
        )
    return "Signalmodus · Position aktiv: Eine bestätigte Einstiegslage erscheint als NACHKAUFEN statt KAUFEN."


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
def _automatic_day_chart(store: DataStore) -> None:
    try:
        quote, trades, fallback_active = _live_market_data()
        candles = market_day_candles(trades, quote)
    except ProviderError:
        st.error("Der Live-Tageschart ist gerade nicht erreichbar. Die App versucht es in zehn Sekunden erneut.")
        return

    _render_market_strip()
    position = _render_instrument_header(store, quote, fallback_active)
    frames_data, errors, provider, symbol, venue = _cached_context_data()
    bundle = TimeframeBundle(frames_data, errors, provider, symbol, venue)
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

    chart_holder = st.container()
    range_holder = st.container()
    current_period = st.session_state.get("dwave_chart_period", "Intraday")
    if current_period not in PERIOD_OPTIONS:
        current_period = "Intraday"
    with range_holder:
        selected_period = st.segmented_control(
            "Zeitraum",
            options=PERIOD_OPTIONS,
            default=current_period,
            key="dwave_chart_period",
            label_visibility="collapsed",
            width="stretch",
        )
    period_label = str(selected_period or current_period)

    with chart_holder:
        style_column, interval_column, overlay_column = st.columns(
            [1.3, 3.4, 4.7],
            vertical_alignment="bottom",
        )
        with style_column:
            chart_style = st.segmented_control(
                "Darstellung",
                options=("Kerzen", "Linie"),
                default="Kerzen",
                key="dwave_chart_style",
                label_visibility="collapsed",
                width="stretch",
            )
        interval_options = PERIOD_INTERVALS[period_label]
        with interval_column:
            candle_minutes = st.pills(
                "Kerzenintervall",
                options=interval_options,
                default=DEFAULT_INTERVAL[period_label],
                format_func=DISPLAY_INTERVAL_LABELS.get,
                key=f"dwave_interval_{period_label}",
                label_visibility="collapsed",
                width="stretch",
            )
        with overlay_column:
            overlays = st.pills(
                "Werkzeuge",
                options=("EMA", "Prognose", "Signale", "Position"),
                selection_mode="multi",
                default=("Prognose", "Signale", "Position"),
                key="dwave_chart_overlays",
                label_visibility="collapsed",
                width="stretch",
            )
        selected_minutes = int(candle_minutes or DEFAULT_INTERVAL[period_label])
        try:
            display_candles = select_display_candles(
                bundle.frames,
                candles,
                period=period_label,
                interval_minutes=selected_minutes,
            )
        except ValueError as exc:
            st.warning(f"{exc} Deshalb bleibt vorübergehend der heutige 5-Minuten-Chart sichtbar.")
            period_label = "Intraday"
            selected_minutes = 5
            display_candles = resample_intraday_candles(candles, 5)

        figure = day_signal_chart(
            display_candles,
            quote,
            signal,
            position,
            events,
            selected_minutes,
            period_label=period_label,
            data_is_resampled=True,
            chart_style=str(chart_style or "Kerzen"),
            overlays=set(overlays or ()),
        )
        st.plotly_chart(
            figure,
            width="stretch",
            config={
                "displaylogo": False,
                "displayModeBar": True,
                "scrollZoom": True,
                "responsive": True,
                "modeBarButtonsToAdd": [
                    "drawline",
                    "drawopenpath",
                    "drawrect",
                    "eraseshape",
                    "toggleSpikelines",
                ],
                "toImageButtonOptions": {"format": "png", "filename": "D-Wave-Chart", "scale": 2},
            },
            key=f"dwave_professional_chart_{period_label}_{selected_minutes}_{chart_style}",
        )
        quote_time = (quote.quoted_at or quote.fetched_at).astimezone(ZoneInfo("Europe/Berlin"))
        source = f"{quote.venue} · Ersatzquelle" if fallback_active else f"{quote.venue} · Hauptquelle"
        st.caption(
            f"{source} · Kurszeit {quote_time:%H:%M:%S} · automatisch alle 10 Sekunden · "
            "Zeichnen, Zoom, Pan, Crosshair und PNG-Export über die Chartleiste · keine automatische Order"
        )
        st.caption(_signal_mode_text(position, quote))
        st.caption(_validation_text(validation))


def focus_page(store: DataStore) -> None:
    _automatic_day_chart(store)
