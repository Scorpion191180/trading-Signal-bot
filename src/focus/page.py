"""Einzige, bewusst reduzierte Streamlit-Seite für D-Wave Quantum."""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from src.data import ProviderError, YFinanceMarketDataProvider
from src.database import DataStore

from .analysis import (
    DWAVE_INSTRUMENT,
    SPEC_BY_KEY,
    FocusPosition,
    analyze_timeframes,
    build_intraday_signal,
)
from .charts import focus_chart
from .data import TimeframeBundle, load_dwave_timeframes
from .quote import LiveQuote, TradegateQuoteProvider


@st.cache_data(ttl=60, show_spinner=False)
def _cached_market_data() -> TimeframeBundle:
    return load_dwave_timeframes(YFinanceMarketDataProvider())


def _live_quote() -> LiveQuote:
    return TradegateQuoteProvider().quote(DWAVE_INSTRUMENT.isin)


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.3f} €".replace(",", "X").replace(".", ",").replace("X", ".")


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
            reference_market=DWAVE_INSTRUMENT.venue,
            notes="Kurzfristige D-Wave-Beobachtung",
        )


def _trend_badge(label: str, score: float, trend: str) -> None:
    icon = "↗" if trend == "Aufwärts" else "↘" if trend == "Abwärts" else "→"
    st.metric(label, f"{icon} {score:.0f}/100", trend)


@st.fragment(run_every=10)
def _live_quote_panel(fallback_price: float | None = None) -> None:
    st.subheader("Livekurs für die Ausführung")
    try:
        quote = _live_quote()
    except ProviderError as exc:
        st.warning(
            "Tradegate ist gerade nicht erreichbar. "
            f"Als Fallback bleibt die letzte Chartkerze sichtbar ({_money(fallback_price)})."
        )
        st.caption(f"Technischer Abruffehler: {exc}")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kaufen · Brief", _money(quote.ask))
    c2.metric("Verkaufen · Geld", _money(quote.bid))
    c3.metric("Letzter Umsatz", _money(quote.last))
    c4.metric("Spread", f"{_money(quote.spread)} · {quote.spread_percent:.2f} %")
    sizes: list[str] = []
    if quote.bid_size is not None:
        sizes.append(f"Geld-Stückzahl {quote.bid_size:,.0f}".replace(",", "."))
    if quote.ask_size is not None:
        sizes.append(f"Brief-Stückzahl {quote.ask_size:,.0f}".replace(",", "."))
    st.caption(
        f"{quote.provider} · Abruf {quote.fetched_at:%H:%M:%S} UTC · automatische Aktualisierung alle 10 Sekunden"
        + (" · " + " · ".join(sizes) if sizes else "")
    )
    if quote.spread_percent >= 0.8:
        st.warning("Der aktuelle Spread ist für einen 5–30-Minuten-Trade groß. Nicht unlimitiert kaufen.")


def focus_page(store: DataStore) -> None:
    instrument = DWAVE_INSTRUMENT
    st.title("D-Wave Quantum · Kurzfrist-Signal")
    st.caption(
        f"{instrument.exchange_symbol} · deutscher Markt · {instrument.currency} · "
        f"WKN {instrument.wkn} · geplante Haltedauer 5–30 Minuten"
    )

    stored = _stored_position(store)
    with st.expander("Meine Position", expanded=stored is not None):
        invested = st.toggle("Ich bin bereits investiert", value=stored is not None)
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
        if st.button("Positionsstatus speichern", width="stretch"):
            _save_position(
                store,
                invested=invested,
                average_price=average_price,
                quantity=quantity,
            )
            st.success("Positionsstatus gespeichert.")
            st.rerun()

    position = FocusPosition(
        invested=invested,
        average_price=average_price if invested else None,
        quantity=quantity if invested else None,
    )
    if st.button("Kurse jetzt aktualisieren", type="primary", width="stretch"):
        _cached_market_data.clear()

    with st.spinner("Prüfe 1 Minute bis Monatschart …"):
        bundle = _cached_market_data()
    st.caption(f"Aktuell ausgewerteter Handelsplatz: **{bundle.venue}** · Datensymbol `{bundle.symbol}`")
    analyses, enriched, analysis_errors = analyze_timeframes(bundle.frames)
    errors = {**bundle.errors, **analysis_errors}
    signal = build_intraday_signal(analyses, enriched, position)

    _live_quote_panel(signal.current_price or None)
    st.caption(
        "Geld und Brief oben sind der laufende Tradegate-Markt. Die folgende Analyse basiert auf abgeschlossenen "
        "Chartkerzen und bleibt bei alten Minutenkerzen vorsorglich gesperrt."
    )

    day_frame = bundle.frames.get("1d")
    day_change = None
    if day_frame is not None and len(day_frame) >= 2:
        day_change = (float(day_frame["close"].iloc[-1]) / float(day_frame["close"].iloc[-2]) - 1) * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Letzte 1-Min.-Kerze", _money(signal.current_price))
    c2.metric("Letzter Tag", f"{day_change:+.2f} %" if day_change is not None else "—")
    c3.metric("Signalstärke", f"{signal.score:.0f}/100", signal.strength)
    if position.invested and position.average_price:
        pnl_pct = (signal.current_price / position.average_price - 1) * 100
        st.caption(f"Deine Position liegt auf Basis der letzten Chartkerze bei **{pnl_pct:+.2f} %** vor Gebühren und Spread.")

    st.markdown(
        f"""
        <div style="border:2px solid {signal.color};border-radius:16px;padding:20px 22px;margin:12px 0;
                    background:linear-gradient(135deg,{signal.color}18,transparent)">
          <div style="font-size:.82rem;letter-spacing:.08em;opacity:.72">AKTUELLES TECHNISCHES SIGNAL</div>
          <div style="font-size:1.65rem;font-weight:750;color:{signal.color};margin:.2rem 0">{signal.headline}</div>
          <div>Zeithorizont: <b>{signal.holding_period}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for reason in signal.reasons:
        st.write("• " + reason)
    st.warning(signal.warning)

    if signal.stop_loss is not None:
        c1, c2, c3 = st.columns(3)
        if signal.entry_low is not None and signal.entry_high is not None:
            c1.metric("Einstiegszone", f"{_money(signal.entry_low)} – {_money(signal.entry_high)}")
        else:
            c1.metric("Aktion", signal.action)
        c2.metric("Technischer Stop", _money(signal.stop_loss))
        c3.metric("Technisches Ziel", _money(signal.target))

    st.subheader("Kurzfristige Bestätigung")
    columns = st.columns(3)
    for column, key in zip(columns, ("1m", "5m", "15m"), strict=True):
        with column:
            analysis = analyses.get(key)
            if analysis:
                _trend_badge(analysis.label, analysis.score, analysis.trend)
            else:
                st.metric(SPEC_BY_KEY[key].label, "Fehlt")

    with st.expander("Übergeordnete Filter · nur zur Risikoprüfung"):
        context_columns = st.columns(4)
        for column, key in zip(context_columns, ("1h", "1d", "1wk", "1mo"), strict=True):
            with column:
                analysis = analyses.get(key)
                if analysis:
                    _trend_badge(analysis.label, analysis.score, analysis.trend)
                else:
                    st.metric(SPEC_BY_KEY[key].label, "Fehlt")
        st.caption("Diese Ebenen verlängern den Trade nicht. Sie verhindern nur einen Einstieg gegen einen sehr starken Trend.")

    st.subheader("Chart")
    available_labels = {
        SPEC_BY_KEY[key].label: key
        for key in ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo")
        if key in analyses and key in enriched
    }
    if available_labels:
        selected_label = st.selectbox(
            "Chartansicht",
            list(available_labels),
            index=min(1, len(available_labels) - 1),
            label_visibility="collapsed",
        )
        selected_key = available_labels[selected_label]
        selected_analysis = analyses[selected_key]
        st.plotly_chart(
            focus_chart(enriched[selected_key], selected_analysis, signal),
            width="stretch",
            config={"displaylogo": False},
        )
        st.info("Hinweis im Chart: " + " · ".join(selected_analysis.reasons[:2]))
        if selected_analysis.warnings:
            st.caption("Achtung: " + " · ".join(selected_analysis.warnings))
    else:
        st.error("Es konnte keine Chartansicht aufgebaut werden.")

    if errors:
        with st.expander("Datenprobleme"):
            for key, message in errors.items():
                st.write(f"**{SPEC_BY_KEY.get(key).label if key in SPEC_BY_KEY else key}:** {message}")
    st.caption(
        f"Quellen: Tradegate BSX Level 1 (Livekurs) und {bundle.provider} (Chartkerzen) · "
        f"Auswertung {datetime.now(UTC):%d.%m.%Y %H:%M UTC} · "
        "keine automatische Order und keine Anlageberatung. Bei verzögerten Daten wird kein Signal freigegeben."
    )
