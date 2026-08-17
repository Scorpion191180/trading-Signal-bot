"""Auf einen automatisch aktualisierten D-Wave-Tageschart reduzierte Seite."""

from __future__ import annotations

import warnings
from dataclasses import asdict
from datetime import UTC, datetime, time
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from sqlalchemy import text

from src.data import ProviderError, YFinanceMarketDataProvider
from src.database import DataStore
from src.database.models import FocusBotStatus

from .analysis import (
    DWAVE_INSTRUMENT,
    ExternalMarketContext,
    FocusPosition,
    IntradaySignal,
    analyze_timeframes,
    build_market_signal,
)
from .charts import day_signal_chart
from .context import FocusContextProvider
from .data import TimeframeBundle, load_dwave_timeframes
from .display import (
    DEFAULT_INTERVAL,
    DISPLAY_INTERVAL_LABELS,
    PERIOD_COMPACT_LABELS,
    PERIOD_INTERVALS,
    select_display_candles,
)
from .lang_schwarz import LangSchwarzQuoteProvider
from .paper import PAPER_STRATEGY_VERSION, PaperAccount, current_paper_account, paper_order_events
from .quote import (
    LiveQuote,
    TradegateQuoteProvider,
    market_day_candles,
    resample_intraday_candles,
)
from .replay import replay_focus_day
from .stock3 import Stock3LangSchwarzProvider

COMPACT_PERIOD_OPTIONS = ("Intraday", "1W", "1M", "3M", "1J", "Max")
UI_REFRESH_SECONDS = 1

_ZOOM_TRACKER_JS = """
export default function(component) {
    const {data, setStateValue} = component;
    let activePlot = null;
    let resetButtons = [];
    let ranges = data.ranges || {};

    const clearRanges = () => {
        ranges = {};
        setStateValue('ranges', null);
    };

    const saveRanges = (event) => {
        const next = {...ranges};
        const xReset = event['xaxis.autorange'] === true;
        const yReset = event['yaxis.autorange'] === true;
        if (xReset) delete next.x;
        if (yReset) delete next.y;
        if (event['xaxis.range[0]'] !== undefined && event['xaxis.range[1]'] !== undefined) {
            next.x = [event['xaxis.range[0]'], event['xaxis.range[1]']];
        }
        if (event['yaxis.range[0]'] !== undefined && event['yaxis.range[1]'] !== undefined) {
            next.y = [event['yaxis.range[0]'], event['yaxis.range[1]']];
        }
        ranges = next;
        setStateValue('ranges', Object.keys(next).length ? next : null);
    };

    const attach = () => {
        const wrapper = document.querySelector(`.st-key-${CSS.escape(data.chartKey)}`);
        const plot = wrapper?.querySelector('.js-plotly-plot');
        if (!plot) return;
        if (plot !== activePlot && typeof plot.on === 'function') {
            if (activePlot && typeof activePlot.removeListener === 'function') {
                activePlot.removeListener('plotly_relayout', saveRanges);
            }
            plot.on('plotly_relayout', saveRanges);
            activePlot = plot;
        }
        const nextResetButtons = Array.from(
            wrapper.querySelectorAll('[data-title="Reset axes"], [data-title="Autoscale"]')
        );
        if (nextResetButtons.some((button, index) => button !== resetButtons[index])) {
            resetButtons.forEach((button) => button.removeEventListener('click', clearRanges, true));
            resetButtons = nextResetButtons;
            resetButtons.forEach((button) => button.addEventListener('click', clearRanges, true));
        }
    };

    attach();
    const observer = new MutationObserver(attach);
    observer.observe(document.body, {childList: true, subtree: true});
    return () => {
        observer.disconnect();
        if (activePlot && typeof activePlot.removeListener === 'function') {
            activePlot.removeListener('plotly_relayout', saveRanges);
        }
        resetButtons.forEach((button) => button.removeEventListener('click', clearRanges, true));
    };
}
"""
_ZOOM_TRACKER = st.components.v2.component(
    "focus_chart_zoom_tracker",
    html="<span></span>",
    css=":host { display: none !important; }",
    js=_ZOOM_TRACKER_JS,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_context_data() -> tuple[dict[str, pd.DataFrame], dict[str, str], str, str, str]:
    """Cached nur serialisierbare Werte, damit ein Code-Reload keine alten Klassentypen festhält."""

    bundle = load_dwave_timeframes(YFinanceMarketDataProvider())
    return bundle.frames, bundle.errors, bundle.provider, bundle.symbol, bundle.venue


@st.cache_data(ttl=1, show_spinner=False)
def _cached_lang_schwarz_snapshot() -> tuple[dict[str, object], pd.DataFrame]:
    """Vermeidet Dataclass-Objekte im Streamlit-Cache über Code-Reloads hinweg."""

    snapshot = LangSchwarzQuoteProvider().snapshot(DWAVE_INSTRUMENT.isin)
    return asdict(snapshot.quote), snapshot.trades


@st.cache_data(ttl=1, show_spinner=False)
def _cached_stock3_quote() -> dict[str, object]:
    """Liefert den L&S-Bid-Kurs des frei sichtbaren stock3-D-Wave-Charts."""

    return asdict(Stock3LangSchwarzProvider().quote())


@st.cache_data(ttl=300, show_spinner=False)
def _cached_stock3_history(resolution_seconds: int) -> pd.DataFrame:
    return Stock3LangSchwarzProvider().history(resolution_seconds)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_stock3_minute_history() -> pd.DataFrame:
    return Stock3LangSchwarzProvider().history(60)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_today_replay() -> dict[str, object]:
    """Berechnet den v6-Tages-Replay nur auf ausdrücklichen Klick und cached das Ergebnis."""

    provider = Stock3LangSchwarzProvider()
    result = replay_focus_day(
        bid_minutes=provider.history(60),
        ask_minutes=provider.history(60, quote_type="ask"),
        five_minutes=provider.history(300),
        hourly=provider.history(3600),
        daily=provider.history(86400),
    )
    return asdict(result)


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


@st.cache_data(ttl=300, show_spinner=False)
def _cached_external_context() -> dict[str, object]:
    context, _news_items = FocusContextProvider().snapshot()
    return asdict(context)


def _latest_trading_day(frame: pd.DataFrame, quote: LiveQuote) -> pd.DataFrame:
    """Schneidet die Historie auf den Handelstag der laufenden L&S-Quotation zu."""

    local_index = frame.index.tz_convert("Europe/Berlin")
    quote_date = (quote.quoted_at or quote.fetched_at).astimezone(ZoneInfo("Europe/Berlin")).date()
    selected = frame.loc[local_index.date == quote_date].copy()
    if selected.empty:
        latest_date = local_index[-1].date()
        selected = frame.loc[local_index.date == latest_date].copy()
    selected.attrs.update(frame.attrs)
    return selected


def _apply_live_quote(candles: pd.DataFrame, quote: LiveQuote) -> pd.DataFrame:
    """Aktualisiert die laufende Minutenkerze bei jedem Sekunden-Refresh mit dem echten Bid."""

    if candles.empty:
        return candles
    updated = candles.copy()
    quote_time = pd.Timestamp(quote.quoted_at or quote.fetched_at).floor("min")
    quote_time = quote_time.tz_localize("UTC") if quote_time.tzinfo is None else quote_time.tz_convert("UTC")
    if quote_time not in updated.index:
        previous_close = float(updated["close"].iloc[-1])
        updated.loc[quote_time, ["open", "high", "low", "close", "volume"]] = [
            previous_close,
            max(previous_close, quote.bid),
            min(previous_close, quote.bid),
            quote.bid,
            0.0,
        ]
    else:
        updated.loc[quote_time, "high"] = max(float(updated.loc[quote_time, "high"]), quote.bid)
        updated.loc[quote_time, "low"] = min(float(updated.loc[quote_time, "low"]), quote.bid)
        updated.loc[quote_time, "close"] = quote.bid
    updated = updated.sort_index()
    updated.attrs.update(candles.attrs)
    return updated


def _live_market_data() -> tuple[LiveQuote, pd.DataFrame, bool, str]:
    """Verwendet L&S-Bid primär und fällt gestuft auf Abschlussquellen zurück."""

    try:
        quote = LiveQuote(**_cached_stock3_quote())
        candles = _latest_trading_day(_cached_stock3_minute_history(), quote)
        if len(candles) < 30:
            raise ProviderError("Die öffentliche L&S-Bid-Historie enthält zu wenige Tageskerzen.")
        return quote, _apply_live_quote(candles, quote), False, "stock3 · L&S Bid"
    except ProviderError as stock3_error:
        stock3_error_message = str(stock3_error)

    try:
        quote_data, trades = _cached_lang_schwarz_snapshot()
        quote = LiveQuote(**quote_data)
        return quote, market_day_candles(trades, quote), True, "L&S Abschlüsse"
    except ProviderError as primary_error:
        try:
            fallback = TradegateQuoteProvider()
            quote = fallback.quote(DWAVE_INSTRUMENT.isin)
            candles = market_day_candles(_cached_tradegate_day_trades(), quote)
            return quote, candles, True, "Tradegate BSX Abschlüsse"
        except ProviderError as fallback_error:
            raise ProviderError(
                f"stock3/L&S Bid: {stock3_error_message}; Lang & Schwarz: {primary_error}; "
                f"Tradegate: {fallback_error}"
            ) from fallback_error


def _stock3_context_frames(fallback_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Ersetzt Yahoo-Zeitebenen, soweit echte historische L&S-Bid-Kerzen vorliegen."""

    frames = dict(fallback_frames)
    try:
        five_minutes = _cached_stock3_history(300)
    except ProviderError:
        pass
    else:
        frames["5m"] = five_minutes
        frames["15m"] = resample_intraday_candles(five_minutes, 15)
    try:
        frames["1h"] = _cached_stock3_history(3600)
    except ProviderError:
        pass
    try:
        frames["1d"] = _cached_stock3_history(86400)
    except ProviderError:
        pass
    return frames


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


def _render_instrument_header(
    store: DataStore,
    quote: LiveQuote,
    fallback_active: bool,
    source_name: str,
) -> FocusPosition:
    change = quote.change_percent or 0.0
    change_color = "#58c981" if change >= 0 else "#e06469"
    source_badge = "Ersatzquelle" if fallback_active else "L&S Bid"
    header_column, position_column = st.columns([8.1, 1.9], vertical_alignment="center")
    header_column.markdown(
        '<div class="instrument-header">'
        '<div class="instrument-name">D-Wave Quantum <span>⌄</span></div>'
        f'<div class="venue-name">{quote.venue} <span>⌄</span><small>{source_badge}</small></div>'
        f'<div class="live-price">{quote.bid:.3f} € '
        f'<span style="color:{change_color}">{change:+.2f} %</span>'
        f'<small>{source_name} · Brief {quote.ask:.3f}</small></div>'
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
    """Trennt das neutrale Marktsignal klar von der privaten Position."""

    if not position.invested:
        return "KAUFEN/VERKAUFEN-Marktsignal und 2.000-€-Papierkonto laufen unabhängig von einer privaten Position."
    distance = (
        (quote.bid / position.average_price - 1) * 100
        if position.average_price is not None and position.average_price > 0
        else 0.0
    )
    return (
        "KAUFEN/VERKAUFEN-Marktsignal unabhängig von deiner privaten Position · "
        f"private Position aktuell {distance:+.1f} % zum Einstand"
    )


def _local_trade_time(value: datetime) -> datetime:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.astimezone(ZoneInfo("Europe/Berlin"))


@st.dialog("Bot-Position und Trades", width="large")
def _render_trade_history_dialog(
    store: DataStore,
    account: PaperAccount,
    quote: LiveQuote,
) -> None:
    orders = store.list_orders(account.portfolio_id, limit=200)
    trades = store.list_trades(account.portfolio_id)
    open_buy = next((order for order in orders if order.side == "BUY"), None)
    invested = (
        open_buy.gross_value + open_buy.fees
        if account.quantity > 0 and open_buy is not None
        else (account.average_price or 0.0) * account.quantity
    )
    open_value = account.quantity * quote.bid
    open_result = open_value - invested
    open_color = "#58c981" if open_result >= 0 else "#e06469"
    position_label = (
        f"{account.quantity:.3f} Stück zu {account.average_price:.3f} €"
        if account.quantity > 0 and account.average_price is not None
        else "Der Bot ist aktuell nicht investiert"
    )
    st.markdown(
        '<div class="trade-overview">'
        f'<span><small>STARTVERMÖGEN</small><b>{account.initial_capital:.2f} €</b></span>'
        f'<span><small>DEPOTWERT</small><b>{account.equity:.2f} €</b></span>'
        f'<span><small>AKTUELL INVESTIERT</small><b>{invested:.2f} €</b></span>'
        f'<span><small>POSITIONSWERT</small><b>{open_value:.2f} €</b></span>'
        f'<span><small>OFFENES ERGEBNIS</small><b style="color:{open_color}">'
        f'{open_result:+.2f} €</b></span>'
        f'<span><small>KOSTEN BISHER</small><b>{account.total_transaction_costs:.2f} €</b></span>'
        '</div>'
        f'<div class="trade-position-line">{position_label}</div>',
        unsafe_allow_html=True,
    )
    trades_tab, orders_tab = st.tabs(("Abgeschlossene Trades", "Alle Orders"))
    with trades_tab:
        if not trades:
            st.info("Noch kein abgeschlossener Trade. Eine offene Position steht oben im Fenster.")
        for number, trade in enumerate(trades, start=1):
            entry_at = _local_trade_time(trade.entry_time)
            exit_at = _local_trade_time(trade.exit_time)
            held_minutes = max(int((exit_at - entry_at).total_seconds() // 60), 0)
            result_color = "#58c981" if trade.pnl_eur >= 0 else "#e06469"
            purchase_value = trade.entry_price * trade.quantity
            st.markdown(
                '<div class="trade-card">'
                '<div class="trade-card-head">'
                f'<b>Trade #{number}</b>'
                f'<strong style="color:{result_color}">{trade.pnl_eur:+.2f} € '
                f'({trade.pnl_pct:+.2f} %)</strong>'
                '</div><div class="trade-grid">'
                f'<span><small>EINSTIEG</small><b>{entry_at:%d.%m. · %H:%M}</b>'
                f'<em>{trade.entry_price:.3f} €</em></span>'
                f'<span><small>AUSSTIEG</small><b>{exit_at:%d.%m. · %H:%M}</b>'
                f'<em>{trade.exit_price:.3f} €</em></span>'
                f'<span><small>STÜCK</small><b>{trade.quantity:.3f}</b></span>'
                f'<span><small>KAUFWERT</small><b>{purchase_value:.2f} €</b></span>'
                f'<span><small>DAUER</small><b>{held_minutes} Min</b></span>'
                f'<span><small>GEBÜHREN</small><b>{trade.fees:.2f} €</b></span>'
                '</div>'
                f'<p><b>Einstieg:</b> {escape(trade.entry_reason)}<br>'
                f'<b>Ausstieg:</b> {escape(trade.exit_reason)}</p>'
                '</div>',
                unsafe_allow_html=True,
            )

    with orders_tab:
        if not orders:
            st.info("Der Bot hat noch keine Order ausgeführt.")
        for order in orders:
            executed_at = _local_trade_time(order.executed_at)
            side_label = "KAUF" if order.side == "BUY" else "VERKAUF"
            side_color = "#58c981" if order.side == "BUY" else "#e06469"
            st.markdown(
                '<div class="trade-card">'
                '<div class="trade-card-head">'
                f'<b style="color:{side_color}">{side_label}</b>'
                f'<span>{executed_at:%d.%m.%Y · %H:%M}</span>'
                '</div><div class="trade-grid">'
                f'<span><small>STÜCK</small><b>{order.quantity:.3f}</b></span>'
                f'<span><small>AUSFÜHRUNG</small><b>{order.execution_price:.3f} €</b></span>'
                f'<span><small>ORDERWERT</small><b>{order.gross_value:.2f} €</b></span>'
                f'<span><small>GEBÜHR</small><b>{order.fees:.2f} €</b></span>'
                f'<span><small>SPREAD</small><b>{order.spread_cost:.2f} €</b></span>'
                f'<span><small>PUFFER</small><b>{order.slippage_cost:.2f} €</b></span>'
                '</div>'
                f'<p>{escape(order.reason)}</p>'
                '</div>',
                unsafe_allow_html=True,
            )


def _render_paper_account(
    store: DataStore,
    account: PaperAccount,
    quote: LiveQuote,
    bot_status: FocusBotStatus | None,
    signal: IntradaySignal,
) -> None:
    portfolio = store.get_portfolio(account.portfolio_id)
    bot_enabled = bool(portfolio.active)
    service_color = "#e06469"
    service_text = "BOT AUS"
    bot_status_is_fresh = False
    if bot_enabled and bot_status is not None:
        heartbeat = bot_status.last_heartbeat
        heartbeat = heartbeat.replace(tzinfo=UTC) if heartbeat.tzinfo is None else heartbeat.astimezone(UTC)
        heartbeat_age = (datetime.now(UTC) - heartbeat).total_seconds()
        heartbeat_time = heartbeat.astimezone(ZoneInfo("Europe/Berlin"))
        bot_status_is_fresh = heartbeat_age <= 180
        if heartbeat_age <= 180 and bot_status.run_state == "ERROR":
            service_text = f"BOT-FEHLER · {heartbeat_time:%H:%M}"
        elif heartbeat_age <= 180 and bot_status.run_state == "WARMUP":
            service_color = "#f59e0b"
            service_text = f"BOT LÄDT DATEN · {heartbeat_time:%H:%M}"
        elif heartbeat_age <= 180:
            service_color = "#58c981"
            mode = "PAUSE" if bot_status.run_state == "PAUSED" else bot_status.signal_action
            service_text = f"BOT EIN · {mode} · {heartbeat_time:%H:%M}"
        else:
            service_text = f"BOT OHNE KONTAKT · {heartbeat_time:%H:%M}"
    elif bot_enabled:
        service_text = "BOT STARTET"
    display_state = (
        bot_status.account_state if bot_enabled and bot_status is not None and bot_status_is_fresh else account.state
    )
    result_color = "#58c981" if account.result_eur >= 0 else "#e06469"
    signal_color = "#58c981" if signal.action == "BUY" else "#e06469" if signal.action == "SELL" else "#f59e0b"
    signal_label = {"BUY": "KAUFEN", "SELL": "VERKAUFEN"}.get(signal.action, "WARTEN")
    position_text = (
        f"{account.quantity:.3f} Stk. @ {account.average_price:.3f} €"
        if account.average_price is not None
        else "keine Position"
    )
    st.markdown(
        '<div class="bot-console">'
        f'<span class="bot-service" style="color:{service_color}">● {service_text}</span>'
        f'<span class="bot-signal"><small>SIGNAL</small> '
        f'<b style="color:{signal_color}">{signal_label} · {signal.score:.0f}/100</b></span>'
        f"<span><small>TREND</small> <b>{escape(signal.forecast_direction.title())}</b></span>"
        f"<span><small>KURS</small> <b>{quote.bid:.3f} €</b></span>"
        f"<span><small>DEPOT</small> <b>{account.equity:.2f} €</b></span>"
        f'<span><small>ERGEBNIS</small> <b style="color:{result_color}">'
        f"{account.result_eur:+.2f} € · {account.result_percent:+.2f} %</b></span>"
        f"<span><small>STATUS</small> <b>{display_state}</b></span>"
        f"<span><small>POSITION</small> <b>{position_text}</b></span>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="bot_controls"):
        toggle_column, trades_column, reset_column = st.columns(3, gap="small")
        toggle_label = "Bot stoppen" if bot_enabled else "Bot starten"
        toggle_icon = ":material/pause:" if bot_enabled else ":material/play_arrow:"
        if toggle_column.button(
            toggle_label,
            icon=toggle_icon,
            type="primary" if not bot_enabled else "secondary",
            width="stretch",
            key="dwave_toggle_bot",
        ):
            new_state = not bot_enabled
            store.set_portfolio_active(account.portfolio_id, new_state)
            store.update_focus_bot_status(
                bot_key="dwave-paper",
                run_state="STARTING" if new_state else "DISABLED",
                signal_action=signal.action,
                signal_score=signal.score,
                account_state=account.state,
                message=(
                    "Vom Benutzer eingeschaltet · nächster Prüfzyklus folgt"
                    if new_state
                    else "Vom Benutzer ausgeschaltet · keine automatischen Orders"
                ),
                heartbeat_at=datetime.now(UTC),
            )
            st.rerun()
        if trades_column.button(
            "Trades",
            icon=":material/receipt_long:",
            width="stretch",
            key="dwave_open_trades",
        ):
            _render_trade_history_dialog(store, account, quote)
        with reset_column.popover(
            "Kapital / Reset",
            icon=":material/account_balance_wallet:",
            width="stretch",
        ):
            starting_capital = st.number_input(
                "Startvermögen in EUR",
                min_value=100.0,
                max_value=1_000_000.0,
                value=float(account.initial_capital),
                step=100.0,
                format="%.2f",
                key="dwave_starting_capital",
            )
            st.caption("Löscht Bot-Position, Orders und Ergebnis und schaltet den Bot aus.")
            if st.button(
                "Depot zurücksetzen",
                icon=":material/restart_alt:",
                type="primary",
                width="stretch",
                key="dwave_reset_bot",
            ):
                store.reset_portfolio(
                    account.portfolio_id,
                    float(starting_capital),
                    active=False,
                )
                store.update_focus_bot_status(
                    bot_key="dwave-paper",
                    run_state="DISABLED",
                    signal_action="WAIT",
                    signal_score=50.0,
                    account_state="CASH",
                    message="Depot zurückgesetzt · Bot ausgeschaltet",
                    heartbeat_at=datetime.now(UTC),
                )
                st.session_state.pop("dwave_today_replay", None)
                st.rerun()


def _validation_text(metrics: dict[str, float | int | None]) -> str:
    recorded = int(metrics["recorded"] or 0)
    completed = int(metrics["completed"] or 0)
    label = "Bisherige Vorwärtsprüfung" if metrics.get("_legacy") else "Vorwärtsprüfung der neuen Strategie v5"
    if completed < 20:
        forecast_label = "Prognose" if recorded == 1 else "Prognosen"
        return (
            f"{label} · {recorded} {forecast_label} gespeichert · "
            f"{completed} nach 15 Minuten ausgewertet · "
            f"aussagekräftiger ab 20 abgeschlossenen Fällen"
        )
    return (
        f"{label} · {completed} echte 15-Minuten-Fälle · "
        f"Richtungstreffer {float(metrics['direction_accuracy']):.1f} % · "
        f"Kurs in Zone {float(metrics['zone_coverage']):.1f} % · "
        "nur später eingetroffene Kurse"
    )


def _versioned_forecast_metrics(store: DataStore) -> dict[str, float | int | None]:
    """Bleibt auch waehrend eines Streamlit-Hot-Reloads auf der neuen Modellversion."""

    try:
        return store.focus_forecast_metrics(
            symbol=DWAVE_INSTRUMENT.exchange_symbol,
            horizon_minutes=15,
            model_version=PAPER_STRATEGY_VERSION,
        )
    except TypeError:
        with store.sessions() as session:
            parameters = {
                "symbol": DWAVE_INSTRUMENT.exchange_symbol,
                "model_version": PAPER_STRATEGY_VERSION,
                "horizon": 15,
                "limit": 200,
            }
            recorded = int(
                session.execute(
                    text(
                        "SELECT COUNT(*) FROM focus_forecasts "
                        "WHERE symbol = :symbol AND model_version = :model_version"
                    ),
                    parameters,
                ).scalar_one()
            )
            outcomes = session.execute(
                text(
                    "SELECT o.direction_hit, o.zone_hit, o.return_percent "
                    "FROM focus_forecast_outcomes o "
                    "JOIN focus_forecasts f ON f.id = o.forecast_id "
                    "WHERE f.symbol = :symbol AND f.model_version = :model_version "
                    "AND o.horizon_minutes = :horizon "
                    "ORDER BY o.observed_at DESC LIMIT :limit"
                ),
                parameters,
            ).all()
        completed = len(outcomes)
        return {
            "recorded": recorded,
            "completed": completed,
            "direction_accuracy": (
                sum(bool(row.direction_hit) for row in outcomes) / completed * 100 if completed else None
            ),
            "zone_coverage": sum(bool(row.zone_hit) for row in outcomes) / completed * 100 if completed else None,
            "average_return": (
                sum(float(row.return_percent) for row in outcomes) / completed if completed else None
            ),
        }


def _render_trend_forecast(signal: IntradaySignal) -> None:
    """Zeigt die kurzfristige Schaetzung kompakt und klar getrennt vom Handelssignal."""

    if not signal.trend_forecasts:
        return
    direction_style = {
        "STEIGEND": ("↗", "#58c981"),
        "FALLEND": ("↘", "#e06469"),
        "SEITWÄRTS": ("→", "#f59e0b"),
    }
    cells: list[str] = []
    for forecast in signal.trend_forecasts:
        arrow, color = direction_style.get(forecast.direction, ("→", "#94a3b8"))
        cells.append(
            '<span class="trend-forecast-cell">'
            f'<b>{forecast.minutes} Min</b> '
            f'<em style="color:{color}">{arrow} {forecast.direction.title()}</em> '
            f'<strong>{forecast.expected_price:.3f} €</strong> '
            f'<small>Zone {forecast.expected_low:.3f}–{forecast.expected_high:.3f} · '
            f'Modellstärke {forecast.confidence:.0f} %</small>'
            '</span>'
        )
    context_color = (
        "#58c981"
        if signal.external_context_score >= 58
        else "#e06469"
        if signal.external_context_score <= 42
        else "#f59e0b"
    )
    context_reason = " · ".join(signal.external_context_reasons[:2]) or "neutraler Ersatzwert"
    latest_headline = signal.latest_news[0] if signal.latest_news else "keine neue relevante Meldung"
    cells.append(
        '<span class="trend-forecast-cell">'
        '<b>Markt & Nachrichten</b> '
        f'<em style="color:{context_color}">{signal.external_context_score:.0f}/100</em> '
        f'<small>{escape(context_reason)} · {escape(latest_headline[:100])}</small>'
        '</span>'
    )
    st.markdown(
        '<div class="trend-forecast-bar"><label>VORAUSSICHTLICHER TREND</label>'
        + "".join(cells)
        + '<i>Schätzung, keine Garantie</i></div>',
        unsafe_allow_html=True,
    )


def _render_replay_summary(summary: dict[str, object]) -> None:
    pnl = float(summary["pnl_eur"])
    color = "#58c981" if pnl > 0 else "#e06469" if pnl < 0 else "#94a3b8"
    first_at = pd.Timestamp(summary["first_candle_at"]).tz_convert("Europe/Berlin")
    last_at = pd.Timestamp(summary["last_candle_at"]).tz_convert("Europe/Berlin")
    completed = int(summary["completed_trades"])
    costs = float(summary["transaction_costs"])
    confirmations = int(summary["confirmation_observations"])
    note = "kein vollständiges v5-Setup" if completed == 0 else f"{completed} abgeschlossene Trades"
    orders = summary.get("orders", ())
    order_labels: list[str] = []
    if isinstance(orders, (list, tuple)):
        for order in orders:
            if not isinstance(order, dict):
                continue
            timestamp = pd.Timestamp(order["executed_at"])
            timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp
            order_labels.append(f"{order['side']} {timestamp.tz_convert('Europe/Berlin'):%H:%M}")
    if order_labels:
        note += " · " + " / ".join(order_labels)
        if any(
            isinstance(order, dict) and "US-Eröffnungs-Reversal" in str(order.get("reason", ""))
            for order in orders
        ):
            note += " · 15:30-Kerze als Live-Bestätigungsproxy"
        if any(
            isinstance(order, dict) and "bullischer Mikrotrend" in str(order.get("reason", ""))
            for order in orders
        ):
            note += " · 17:55-Musterkerze als Live-Bestätigungsproxy"
    st.markdown(
        '<div class="replay-summary-bar"><label>TAGES-REPLAY V6</label>'
        f'<b>{first_at:%H:%M}–{last_at:%H:%M}</b>'
        f'<strong style="color:{color}">{pnl:+.2f} € ({float(summary["pnl_percent"]):+.2f} %)</strong>'
        f'<span>Depot {float(summary["ending_equity"]):.2f} €</span>'
        f'<span>Kosten {costs:.2f} €</span><small>{note} · {confirmations} Bestätigungen · '
        'echte historische L&S-Bid/Ask-Minuten</small>'
        '</div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=UI_REFRESH_SECONDS)
def _automatic_day_chart(store: DataStore) -> None:
    try:
        quote, candles, _fallback_active, _source_name = _live_market_data()
    except ProviderError:
        st.error("Der Live-Tageschart ist gerade nicht erreichbar. Die App versucht es in einer Sekunde erneut.")
        return

    frames_data, errors, provider, symbol, venue = _cached_context_data()
    bundle = TimeframeBundle(frames_data, errors, provider, symbol, venue)
    frames = _stock3_context_frames(bundle.frames)
    frames["1m"] = candles
    five_minutes = resample_intraday_candles(candles, 5)
    fifteen_minutes = resample_intraday_candles(candles, 15)
    if len(five_minutes) >= 35 and frames.get("5m", pd.DataFrame()).attrs.get("provider") != "stock3 · L&S Bid":
        frames["5m"] = five_minutes
    if (
        len(fifteen_minutes) >= 35
        and frames.get("15m", pd.DataFrame()).attrs.get("provider") != "stock3 · L&S Bid"
    ):
        frames["15m"] = fifteen_minutes

    analyses, enriched, _errors = analyze_timeframes(frames)
    try:
        external_context = ExternalMarketContext(**_cached_external_context())
    except Exception:
        external_context = ExternalMarketContext()
    signal = build_market_signal(
        analyses,
        enriched,
        now=datetime.now(UTC),
        live_price=quote.bid,
        session_close=time(23, 0) if quote.venue == "Lang & Schwarz" else time(22, 0),
        spread_percent=(quote.ask - quote.bid) / quote.midpoint * 100,
        order_imbalance=(quote.bid_size - quote.ask_size) / (quote.bid_size + quote.ask_size)
        if quote.bid_size is not None
        and quote.ask_size is not None
        and quote.bid_size + quote.ask_size > 0
        else None,
        require_volume_confirmation=candles.attrs.get("quote_type") != "bid",
        enforce_liquidity_filter=False,
        external_context=external_context,
    )
    paper_account = current_paper_account(store, quote.bid)
    bot_status = store.get_focus_bot_status()
    events = paper_order_events(store, paper_account.portfolio_id, candles.index[-1])
    position = FocusPosition(
        invested=paper_account.quantity > 0,
        average_price=paper_account.average_price,
        quantity=paper_account.quantity or None,
    )
    _render_paper_account(store, paper_account, quote, bot_status, signal)

    current_period = st.session_state.get("dwave_chart_period", "Intraday")
    if current_period not in COMPACT_PERIOD_OPTIONS:
        current_period = "Intraday"
    with st.container(key="chart_toolbar"):
        period_column, interval_column, options_column = st.columns(
            [7.7, 1.55, 0.75],
            vertical_alignment="center",
            gap="small",
        )
        with period_column:
            selected_period = st.pills(
                "Zeitraum",
                options=COMPACT_PERIOD_OPTIONS,
                default=current_period,
                format_func=PERIOD_COMPACT_LABELS.get,
                key="dwave_chart_period",
                label_visibility="collapsed",
                help="Heute, Woche, Monat, Jahr oder gesamte Historie",
                width="stretch",
            )
        period_label = str(selected_period or current_period)
        interval_options = PERIOD_INTERVALS[period_label]
        with interval_column:
            candle_minutes = st.selectbox(
                "Kerzengröße",
                options=interval_options,
                index=interval_options.index(DEFAULT_INTERVAL[period_label]),
                format_func=DISPLAY_INTERVAL_LABELS.get,
                key=f"dwave_interval_{period_label}",
                label_visibility="collapsed",
                help="Zeitspanne einer Kerze",
                width="stretch",
            )
        with options_column:
            with st.popover("⋯", icon=":material/tune:", width="stretch"):
                chart_style = st.segmented_control(
                    "Darstellung",
                    options=("Kerzen", "Linie"),
                    default="Kerzen",
                    key="dwave_chart_style",
                    width="stretch",
                )
                overlays = st.pills(
                    "Einblendungen",
                    options=("EMA", "Prognose", "Zonen", "Signale", "Position"),
                    selection_mode="multi",
                    default=("Prognose", "Zonen", "Signale", "Position"),
                    key="dwave_chart_overlays",
                    width="stretch",
                )
                forecast_horizon = st.select_slider(
                    "Vergleich früherer Prognosen",
                    options=(15, 30, 60, 120),
                    value=60,
                    format_func=lambda value: f"{value} Minuten",
                    key="dwave_forecast_horizon",
                    help="Die violette Linie zeigt, welchen Kurs der Bot damals für diese spätere Zielzeit erwartet hatte.",
                )
    selected_minutes = int(candle_minutes or DEFAULT_INTERVAL[period_label])
    try:
        display_candles = select_display_candles(
            frames,
            candles,
            period=period_label,
            interval_minutes=selected_minutes,
        )
    except ValueError as exc:
        st.warning(f"{exc} Deshalb bleibt vorübergehend der heutige 5-Minuten-Chart sichtbar.")
        period_label = "Intraday"
        selected_minutes = 5
        display_candles = resample_intraday_candles(candles, 5)

    historical_forecasts = store.focus_forecast_chart_points(
        symbol=DWAVE_INSTRUMENT.exchange_symbol,
        horizon_minutes=int(forecast_horizon),
        start_at=pd.Timestamp(display_candles.index[0]).to_pydatetime(),
        end_at=pd.Timestamp(display_candles.index[-1]).to_pydatetime(),
    )

    chart_key = f"dwave_professional_chart_{period_label}_{selected_minutes}_{chart_style}"
    zoom_key = f"{chart_key}_zoom"
    stored_zoom = st.session_state.get(zoom_key, {}).get("ranges")
    zoom_state = _ZOOM_TRACKER(
        key=zoom_key,
        data={"chartKey": chart_key, "ranges": stored_zoom},
        default={"ranges": stored_zoom},
        on_ranges_change=lambda: None,
        width="content",
    )
    axis_ranges = zoom_state.ranges if isinstance(zoom_state.ranges, dict) else None
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
        historical_forecasts=historical_forecasts,
        forecast_horizon_minutes=int(forecast_horizon),
        axis_ranges=axis_ranges,
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
        key=chart_key,
    )


def focus_page(store: DataStore) -> None:
    _automatic_day_chart(store)
