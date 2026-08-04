"""Mobile Seiten der Streamlit-Anwendung."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, date, datetime

import pandas as pd
import streamlit as st

from src.agent import TradingAgent
from src.analysis import SignalAction, add_indicators, analyze_signal
from src.config import STRATEGIES, WEIGHTS, AppSettings
from src.data import (
    MarketDataProvider,
    MarketDataRequest,
    ProviderError,
    recommended_period,
    source_name,
)
from src.database.repositories import DataStore, PortfolioError
from src.portfolio.backtest import run_backtest
from src.portfolio.risk import calculate_position_size

from .charts import candlestick_chart, component_chart

LOGGER = logging.getLogger(__name__)


def _money(value: float) -> str:
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _safe_history(provider: MarketDataProvider, symbol: str, interval: str, period: str, prepost: bool = False) -> pd.DataFrame:
    try:
        frame = provider.history(MarketDataRequest(symbol, interval, period, prepost))
        if reason := frame.attrs.get("fallback_reason"):
            st.warning(f"Primärquelle nicht verwendbar; echte Ersatzquelle aktiv. Details: {reason}")
        return frame
    except ProviderError as exc:
        LOGGER.exception("Datenabruf für %s fehlgeschlagen", symbol)
        st.error(str(exc))
        return pd.DataFrame()


def overview(store: DataStore, provider: MarketDataProvider) -> None:
    st.title("Trading-Signal-Agent")
    st.warning("Experimentelle technische Einschätzungen – keine Anlageberatung und keine echten Orders.")
    portfolios = store.list_portfolios()
    total_initial = sum(item.initial_capital for item in portfolios)
    total_value = sum(store.portfolio_value(item.id) for item in portfolios)
    positions = store.list_positions()
    columns = st.columns(2)
    columns[0].metric("Spielgeld gesamt", _money(total_value), f"{total_value - total_initial:+.2f} €")
    columns[1].metric("Offene Positionen", len(positions))
    columns[0].metric("Freies Kapital", _money(sum(item.cash for item in portfolios)))
    last_run = store.last_agent_run()
    columns[1].metric("Letzter Agentenlauf", last_run.status if last_run else "Noch keiner")
    st.caption(
        f"Datenquellen: {provider.name}"
        + (" · eindeutig als Offline-Test" if provider.is_demo else " · echte Marktdaten, teils verzögert")
    )
    signals = store.list_signals(12)
    st.subheader("Aktuelle Signale")
    if not signals:
        st.info("Noch keine Analysen gespeichert. Starte eine Aktienanalyse oder den Agentenlauf.")
    else:
        for signal in signals[:8]:
            icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "BLOCKED": "⚪"}.get(signal.action, "⚪")
            with st.container(border=True):
                st.write(f"{icon} **{signal.symbol} · {signal.strategy}** — {signal.action} · {signal.score:.1f}/100")
                st.caption(f"{signal.provider} · Konfidenz {signal.confidence:.0f}% · experimentell")
    st.subheader("Strategievergleich")
    for portfolio in portfolios:
        value = store.portfolio_value(portfolio.id)
        st.write(f"**{portfolio.name}:** {_money(value)} ({(value / portfolio.initial_capital - 1) * 100:+.2f} %)")


def real_portfolio(store: DataStore) -> None:
    st.title("Echtes Depot")
    st.info("Nur manuelle Erfassung und Analyse. Die App kann und wird hier keine Order ausführen.")
    with st.expander("Position hinzufügen", expanded=not bool(store.list_real_positions())):
        with st.form("real_position"):
            company = st.text_input("Unternehmen")
            symbol = st.text_input("Tickersymbol").upper()
            c1, c2 = st.columns(2)
            quantity = c1.number_input("Stückzahl", min_value=0.001, value=1.0, step=0.1)
            average = c2.number_input("Ø Kaufkurs", min_value=0.01, value=10.0)
            purchase_date = st.date_input("Kaufdatum", value=date.today())
            c1, c2 = st.columns(2)
            currency = c1.selectbox("Währung", ["EUR", "USD", "CHF", "GBP"])
            isin = c2.text_input("ISIN/WKN (optional)")
            c1, c2 = st.columns(2)
            stop = c1.number_input("Stop-Loss (0 = leer)", min_value=0.0, value=0.0)
            target = c2.number_input("Kursziel (0 = leer)", min_value=0.0, value=0.0)
            market = st.text_input("Referenzmarkt (optional)")
            notes = st.text_area("Eigene Notizen")
            if st.form_submit_button("Position speichern", width="stretch"):
                try:
                    store.add_real_position(
                        company=company,
                        symbol=symbol,
                        quantity=quantity,
                        average_price=average,
                        purchase_date=purchase_date,
                        currency=currency,
                        isin_wkn=isin,
                        reference_market=market,
                        stop_loss=stop or None,
                        target_price=target or None,
                        notes=notes,
                    )
                    st.success("Position gespeichert.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    for position in store.list_real_positions():
        with st.expander(f"{position.symbol} · {position.quantity:g} Stück · {_money(position.quantity * position.average_price)}"):
            st.write(f"Unternehmen: {position.company}")
            st.write(f"Ø Kaufkurs: {position.average_price:.2f} {position.currency}")
            st.write(f"Stop-Loss: {position.stop_loss or 'nicht gesetzt'} · Kursziel: {position.target_price or 'nicht gesetzt'}")
            st.write(position.notes or "Keine Notiz")
            if st.button("Eintrag löschen", key=f"delete-real-{position.id}"):
                store.delete_real_position(position.id)
                st.rerun()


def watchlist(store: DataStore) -> None:
    st.title("Watchlist")
    items = store.list_watchlist()
    with st.expander("Neue Aktie hinzufügen", expanded=not bool(items)):
        with st.form("watchlist-add"):
            symbol = st.text_input("Tickersymbol").upper()
            company = st.text_input("Unternehmen (optional)")
            if st.form_submit_button("Aktie hinzufügen", width="stretch"):
                if symbol in {item.symbol for item in items}:
                    st.error("Diese Aktie ist bereits vorhanden. Einstellungen bitte direkt unten ändern.")
                else:
                    try:
                        store.add_watchlist_item(symbol, company=company)
                        st.success("Aktie hinzugefügt.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    st.caption("Schalter und Intervalle werden sofort gespeichert – ein zusätzlicher Speichern-Button ist nicht nötig.")
    intervals = ["1m", "5m", "15m", "30m", "1h", "1d"]
    for item in items:
        with st.container(border=True):
            st.markdown(f"### {item.symbol}")
            if item.company and item.company != item.symbol:
                st.caption(item.company)
            c1, c2 = st.columns(2)
            trading_allowed = c1.toggle(
                "Spielgeld erlaubt",
                value=item.trading_allowed,
                key=f"watch-trading-{item.id}",
                help="Der Agent darf für diese Aktie ausschließlich virtuelle Orders erzeugen.",
            )
            priority = c2.toggle(
                "Priorisiert",
                value=item.priority,
                key=f"watch-priority-{item.id}",
            )
            interval = st.selectbox(
                "Analyseintervall",
                intervals,
                index=intervals.index(item.interval),
                key=f"watch-interval-{item.id}",
            )
            extended = st.toggle(
                "Vor-/Nachbörse anfragen",
                value=item.extended_hours,
                key=f"watch-extended-{item.id}",
                help="Nur soweit die aktive Datenquelle diese Kurse zuverlässig liefert.",
            )
            changed = (
                trading_allowed != item.trading_allowed
                or priority != item.priority
                or interval != item.interval
                or extended != item.extended_hours
            )
            if changed:
                store.update_watchlist_settings(
                    item.id,
                    priority=priority,
                    trading_allowed=trading_allowed,
                    interval=interval,
                    extended_hours=extended,
                )
                st.toast(f"{item.symbol}: Einstellungen gespeichert.", icon="✅")
            status = "Für virtuelle Trades freigegeben" if trading_allowed else "Nur Analyse"
            st.caption(("⭐ " if priority else "") + status)
            if st.button("Entfernen", key=f"delete-watch-{item.id}"):
                store.delete_watchlist_item(item.id)
                st.rerun()


def agent_portfolio(store: DataStore, agent: TradingAgent) -> None:
    st.title("Agenten-Depot")
    portfolios = store.list_portfolios()
    selected_name = st.selectbox("Strategie-Unterdepot", [item.name for item in portfolios])
    portfolio = next(item for item in portfolios if item.name == selected_name)
    value = store.portfolio_value(portfolio.id)
    c1, c2 = st.columns(2)
    c1.metric("Depotwert", _money(value), f"{value - portfolio.initial_capital:+.2f} €")
    c2.metric("Freies Kapital", _money(portfolio.cash))
    if st.button("Agentenlauf jetzt starten", type="primary", width="stretch"):
        with st.spinner("Analysiere Watchlist und prüfe ausschließlich virtuelle Aktionen …"):
            result = agent.run(force=True)
        if result.errors:
            st.warning("Lauf beendet mit Datenproblemen:\n" + "\n".join(result.errors))
        else:
            st.success(f"{result.signals} Signale, {result.virtual_actions} virtuelle Aktionen.")
        st.rerun()
    positions = store.list_positions(portfolio.id)
    st.subheader("Offene virtuelle Positionen")
    if not positions:
        st.info("Keine Position offen. Käufe erfolgen nur bei freigegebenem Symbol und erfüllten Regeln.")
    for position in positions:
        pnl = (position.current_price - position.average_price) * position.quantity - position.entry_fees_remaining
        with st.expander(f"{position.symbol} · {position.quantity:g} · {pnl:+.2f} €"):
            st.write(f"Einstieg {position.average_price:.4f} · letzter Kurs {position.current_price:.4f}")
            st.write(f"Stop {position.stop_loss:.4f} · Ziel {position.take_profit:.4f}")
            st.caption(
                f"Einstiegsquelle: {position.entry_provider} · letzter Kurs: {position.last_provider} · "
                f"{position.entry_reason}"
            )
            quantity = st.number_input(
                "Zu verkaufende Stückzahl", 0.001, float(position.quantity), float(position.quantity), key=f"sell-qty-{position.id}"
            )
            if st.button("Virtuellen Verkauf ausführen", key=f"sell-{position.id}"):
                try:
                    watchlist_item = next(
                        (item for item in store.list_watchlist() if item.symbol == position.symbol),
                        None,
                    )
                    interval = watchlist_item.interval if watchlist_item else "5m"
                    frame = agent.provider.history(
                        MarketDataRequest(
                            position.symbol,
                            interval,
                            recommended_period(interval),
                            watchlist_item.extended_hours if watchlist_item else False,
                        )
                    )
                    data_timestamp = pd.Timestamp(frame.index[-1]).to_pydatetime()
                    maximum_age = 96 * 60 if interval == "1d" else agent.settings.stale_after_minutes
                    age_minutes = (datetime.now(UTC) - data_timestamp).total_seconds() / 60
                    if age_minutes > maximum_age:
                        raise PortfolioError(
                            f"Manueller Verkauf blockiert: Kursdaten sind {age_minutes:.0f} Minuten alt."
                        )
                    actual_provider = source_name(frame, agent.provider)
                    store.close_position(
                        portfolio_id=portfolio.id,
                        symbol=position.symbol,
                        market_price=float(frame["close"].iloc[-1]),
                        reason="Manueller virtueller Verkauf",
                        signal_score=50,
                        provider=actual_provider,
                        is_demo=agent.provider.is_demo,
                        quantity=quantity,
                    )
                    st.success("Virtueller Verkauf gebucht.")
                    st.rerun()
                except (PortfolioError, ProviderError) as exc:
                    st.error(str(exc))
    with st.expander("Depot zurücksetzen"):
        capital = st.number_input("Neues Startkapital", min_value=100.0, value=float(portfolio.initial_capital), step=100.0)
        confirm = st.checkbox("Ich bestätige das Löschen aller virtuellen Orders und Trades dieses Unterdepots.")
        if st.button("Unwiderruflich zurücksetzen", disabled=not confirm):
            store.reset_portfolio(portfolio.id, capital)
            st.success("Unterdepot zurückgesetzt.")
            st.rerun()


def analysis_page(store: DataStore, provider: MarketDataProvider, settings: AppSettings) -> None:
    st.title("Aktienanalyse")
    symbols = [item.symbol for item in store.list_watchlist()] or ["AAPL"]
    symbol = st.selectbox("Aktie", symbols)
    c1, c2 = st.columns(2)
    interval = c1.selectbox("Zeitebene", ["1m", "5m", "15m", "30m", "1h", "1d"], index=1)
    strategy_name = c2.selectbox("Strategie", list(STRATEGIES))
    period = recommended_period(interval)
    frame = _safe_history(provider, symbol, interval, period)
    if frame.empty:
        return
    result = analyze_signal(
        symbol,
        frame,
        STRATEGIES[strategy_name],
        provider=source_name(frame, provider),
        stale_after_minutes=96 * 60 if interval == "1d" else settings.stale_after_minutes,
    )
    store.record_signal(result)
    color = {SignalAction.BUY: "green", SignalAction.SELL: "red", SignalAction.HOLD: "orange"}.get(result.action, "gray")
    st.markdown(f"### :{color}[{result.action.value} · {result.score:.1f}/100]")
    st.caption(
        f"{result.provider} · Datenstand {result.data_timestamp:%Y-%m-%d %H:%M UTC} · "
        f"Konfidenz {result.confidence:.0f}% · experimentell"
    )
    if result.data_problem:
        st.error("Signal blockiert: " + result.data_problem)
    indicator_data = add_indicators(frame)
    orders = [order for order in store.list_orders(limit=500) if order.symbol == symbol]
    st.plotly_chart(
        candlestick_chart(indicator_data.tail(240), symbol=symbol, zones=result.zones, orders=orders),
        width="stretch",
    )
    c1, c2 = st.columns(2)
    c1.metric("Kurs", f"{result.price:.4f}")
    c2.metric("Trend", result.trend)
    c1.metric("Stop-Loss", f"{result.stop_loss:.4f}" if result.stop_loss else "—")
    c2.metric("Ziel 1", f"{result.target_1:.4f}" if result.target_1 else "—")
    st.write(f"Chance-Risiko-Verhältnis: **{result.reward_risk or '—'}**")
    with st.expander("Punkte im Detail"):
        st.plotly_chart(component_chart(result.components), width="stretch")
        st.json(result.components)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Positive Faktoren**")
        for factor in result.positive_factors:
            st.write("✅ " + factor)
    with c2:
        st.markdown("**Negative Faktoren**")
        for factor in result.negative_factors:
            st.write("⚠️ " + factor)
    if result.action is SignalAction.BUY and result.stop_loss and result.target_1:
        portfolio = next(value for value in store.list_portfolios() if value.strategy == strategy_name)
        positions = store.list_positions(portfolio.id)
        relative_volume = float(indicator_data["relative_volume"].iloc[-1])
        decision = calculate_position_size(
            portfolio_value=store.portfolio_value(portfolio.id),
            available_cash=portfolio.cash,
            entry_price=result.price,
            stop_loss=result.stop_loss,
            profile=STRATEGIES[strategy_name],
            open_positions=len(positions),
            relative_volume=relative_volume,
            data_is_fresh=result.data_problem is None,
            spread_pct=settings.spread_pct,
        )
        st.info(f"Risikoprüfung: {decision.reason} Vorgeschlagen: {decision.quantity:g} Stück.")
        allowed_symbol = next((item for item in store.list_watchlist() if item.symbol == symbol), None)
        if st.button(
            "Virtuellen Kauf ausführen",
            disabled=not decision.allowed or not bool(allowed_symbol and allowed_symbol.trading_allowed),
            width="stretch",
        ):
            try:
                store.open_position(
                    portfolio_id=portfolio.id,
                    symbol=symbol,
                    quantity=decision.quantity,
                    market_price=result.price,
                    stop_loss=result.stop_loss,
                    take_profit=result.target_1,
                    reason="Bestätigtes experimentelles Kaufsignal",
                    signal_score=result.score,
                    weight_version=result.weight_version,
                    provider=result.provider,
                    is_demo=provider.is_demo,
                )
                st.success("Virtueller Kauf ausgeführt. Keine echte Order wurde platziert.")
                st.rerun()
            except PortfolioError as exc:
                st.error(str(exc))


def scanner(store: DataStore, provider: MarketDataProvider, settings: AppSettings) -> None:
    st.title("Markt-Scanner")
    st.caption("Scannt nur die selbst gepflegte Watchlist; kein vollständiger Markt- oder Trade-Republic-Katalog.")
    if not st.button("Watchlist scannen", type="primary", width="stretch"):
        st.info("Der grobe Scan startet nur auf Knopfdruck, um kostenlose Datenquellen zu schonen.")
        return
    rows: list[dict[str, object]] = []
    progress = st.progress(0.0)
    items = store.list_watchlist()
    for index, item in enumerate(items):
        try:
            frame = provider.history(MarketDataRequest(item.symbol, item.interval, recommended_period(item.interval)))
            result = analyze_signal(
                item.symbol,
                frame,
                STRATEGIES["Normal"],
                provider=source_name(frame, provider),
                stale_after_minutes=96 * 60 if item.interval == "1d" else settings.stale_after_minutes,
            )
            indicator_data = add_indicators(frame)
            last = indicator_data.iloc[-1]
            move = (last["close"] / indicator_data["close"].iloc[-2] - 1) * 100
            rows.append(
                {
                    "Symbol": item.symbol,
                    "Signal": result.action.value,
                    "Punkte": result.score,
                    "Bewegung %": round(float(move), 2),
                    "Rel. Volumen": round(float(last["relative_volume"]), 2),
                    "Trend": result.trend,
                }
            )
            store.record_signal(result)
        except (ProviderError, ValueError) as exc:
            rows.append({"Symbol": item.symbol, "Signal": "BLOCKED", "Punkte": 0, "Problem": str(exc)})
        progress.progress((index + 1) / max(len(items), 1))
    st.dataframe(pd.DataFrame(rows).sort_values("Punkte", ascending=False), hide_index=True, width="stretch")


def news_page(store: DataStore) -> None:
    st.title("Nachrichten")
    st.info(
        "Es ist noch keine belastbare echte Nachrichtenquelle konfiguriert. Deshalb zeigt die App hier keine "
        "erfundenen Demo-Meldungen; die Nachrichtenkomponente der Bewertung bleibt neutral."
    )
    st.caption(f"Beobachtete Symbole: {', '.join(value.symbol for value in store.list_watchlist())}")


def strategies_page() -> None:
    st.title("Strategien")
    st.info("Feste Schutzregeln dürfen von einem späteren Lernsystem nicht automatisch außer Kraft gesetzt werden.")
    for profile in STRATEGIES.values():
        with st.expander(f"{profile.name} · {profile.version}", expanded=profile.name == "Normal"):
            st.json(asdict(profile))
    st.subheader(f"Punktegewichtung {WEIGHTS.version}")
    st.json(WEIGHTS.as_dict())
    st.caption("Kontrolliertes Lernen ist in 0.1 noch deaktiviert; es findet keine automatische Parameteränderung statt.")


def backtesting_page(store: DataStore, provider: MarketDataProvider) -> None:
    st.title("Backtesting")
    symbols = [item.symbol for item in store.list_watchlist()] or ["AAPL"]
    symbol = st.selectbox("Aktie", symbols, key="backtest-symbol")
    c1, c2 = st.columns(2)
    interval = c1.selectbox("Intervall", ["5m", "15m", "30m", "1h", "1d"], index=4, key="backtest-interval")
    strategy_name = c2.selectbox("Strategie", list(STRATEGIES), key="backtest-strategy")
    c1, c2 = st.columns(2)
    capital = c1.number_input("Startkapital", min_value=100.0, value=10_000.0, step=100.0)
    fee = c2.number_input("Gebühr pro Order", min_value=0.0, value=1.0, step=0.1)
    c1, c2 = st.columns(2)
    spread = c1.number_input("Spread %", min_value=0.0, value=0.1, step=0.01) / 100
    slippage = c2.number_input("Slippage %", min_value=0.0, value=0.05, step=0.01) / 100
    if not st.button("Backtest starten", type="primary", width="stretch"):
        st.caption("Signale werden auf Kerze t gebildet und frühestens am Open von t+1 ausgeführt.")
        return
    frame = _safe_history(provider, symbol, interval, recommended_period(interval, backtest=True))
    if frame.empty:
        return
    try:
        result = run_backtest(
            frame,
            STRATEGIES[strategy_name],
            initial_capital=capital,
            fee=fee,
            spread_pct=spread,
            slippage_pct=slippage,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    c1, c2 = st.columns(2)
    c1.metric("Endkapital", _money(result.final_capital), f"{result.total_return_pct:+.2f} %")
    c2.metric("Buy & Hold", f"{result.benchmark_return_pct:+.2f} %")
    c1.metric("Trefferquote", f"{result.win_rate_pct:.1f} %")
    c2.metric("Max. Drawdown", f"{result.max_drawdown_pct:.1f} %")
    st.write(f"Trades: **{len(result.trades)}** · Profit Factor: **{result.profit_factor}**")
    st.line_chart(result.equity_curve)
    if result.trades:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Einstieg": trade.entry_time,
                        "Ausstieg": trade.exit_time,
                        "PnL €": round(trade.pnl, 2),
                        "Grund": trade.reason,
                    }
                    for trade in result.trades
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def trade_journal(store: DataStore) -> None:
    st.title("Trade-Journal")
    trades = store.list_trades()
    if not trades:
        st.info("Noch keine abgeschlossenen virtuellen Trades.")
        return
    for trade in trades:
        with st.expander(f"#{trade.id} · {trade.symbol} · {trade.strategy} · {trade.pnl_eur:+.2f} €"):
            st.write(f"Einstieg {trade.entry_price:.4f} → Ausstieg {trade.exit_price:.4f}")
            st.write(
                f"Zeit: {trade.entry_time:%d.%m.%Y %H:%M UTC} → "
                f"{trade.exit_time:%d.%m.%Y %H:%M UTC}"
            )
            st.write(f"Stück {trade.quantity:g} · Ergebnis {trade.pnl_pct:+.2f} % · Gebühren {trade.fees:.2f} €")
            st.write(f"Stop {trade.stop_loss:.4f} · Ziel {trade.take_profit:.4f}")
            st.write(f"Kaufgrund: {trade.entry_reason}")
            st.write(f"Verkaufsgrund: {trade.exit_reason}")
            st.caption(
                f"Quellen: {trade.entry_provider} → {trade.exit_provider} · "
                f"Strategie {trade.strategy_version} · Gewichte {trade.weight_version}"
            )


def settings_page(settings: AppSettings, provider: MarketDataProvider) -> None:
    st.title("Einstellungen")
    st.info("Konfiguration erfolgt in Version 0.1 über Umgebungsvariablen und zentrale versionierte Standardwerte.")
    st.code(
        "\n".join(
            [
                f"DATA_PROVIDER={settings.data_provider}",
                f"APCA_API_KEY_ID={'gesetzt' if settings.alpaca_api_key_id else 'nicht gesetzt'}",
                f"APCA_API_SECRET_KEY={'gesetzt' if settings.alpaca_api_secret_key else 'nicht gesetzt'}",
                f"TWELVE_DATA_API_KEY={'gesetzt' if settings.twelve_data_api_key else 'nicht gesetzt'}",
                f"APP_TIMEZONE={settings.timezone}",
                f"STALE_AFTER_MINUTES={settings.stale_after_minutes}",
                f"STARTING_CAPITAL={settings.starting_capital}",
                f"ORDER_FEE={settings.order_fee}",
                f"SPREAD_PCT={settings.spread_pct}",
                f"SLIPPAGE_PCT={settings.slippage_pct}",
            ]
        )
    )
    st.write(f"Aktive Realdatenkette: **{provider.name}**")
    if not provider.is_demo and not (
        settings.twelve_data_api_key
        or (settings.alpaca_api_key_id and settings.alpaca_api_secret_key)
    ):
        st.info(
            "Aktuell ist nur yfinance aktiv. Für kostenlose Intraday-Fallbacks können Alpaca- oder "
            "Twelve-Data-Schlüssel gesetzt werden."
        )
    st.caption("API-Schlüssel werden nie in der Oberfläche oder im Quellcode gespeichert.")


def system_status(store: DataStore, provider: MarketDataProvider, settings: AppSettings) -> None:
    st.title("Systemstatus")
    last = store.last_agent_run()
    st.success("Datenbank erreichbar und Tabellen initialisiert.")
    st.write(f"Kursdatenanbieter: **{provider.name}**")
    st.write(f"Modus: **{'OFFLINE-TEST' if provider.is_demo else 'kostenlose reale Quellen mit Qualitätsprüfung'}**")
    st.write(f"Analyseintervall: **ca. {settings.analysis_interval_minutes} Minuten**")
    st.write(f"Zeitzone: **{settings.timezone}**")
    if last:
        st.write(f"Letzter Lauf: **{last.status}** · {last.started_at}")
        st.write(f"Signale: {last.generated_signals} · virtuelle Aktionen: {last.virtual_actions}")
        if last.error_details:
            st.warning(last.error_details)
    else:
        st.info("Noch kein Agentenlauf protokolliert.")
    st.warning(
        "Kostenlose Kursquellen können verzögert oder lückenhaft sein. Zu kurze Reihen werden verworfen; "
        "wenn alle passenden Realdatenquellen scheitern, wird das Signal blockiert. Nachrichten sind deaktiviert."
    )
