"""Fuehrt den D-Wave-v8-Replay mit historischen L&S-Spreads aus."""

from __future__ import annotations

import argparse
from datetime import date
from zoneinfo import ZoneInfo

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory
from src.focus.replay import replay_focus_day
from src.focus.stock3 import Stock3LangSchwarzProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="D-Wave-v8-Tages-Replay")
    parser.add_argument(
        "--confirmation-observations",
        type=int,
        default=2,
        help="Historische Minutenbeobachtungen, die ein BUY bestätigen müssen",
    )
    parser.add_argument("--date", type=date.fromisoformat, help="Handelstag im Format JJJJ-MM-TT")
    parser.add_argument(
        "--save-forecasts",
        action="store_true",
        help="Historische Walk-forward-Prognosen für die Chart-Vergleichslinie speichern",
    )
    args = parser.parse_args()
    provider = Stock3LangSchwarzProvider()
    forecast_store = None
    if args.save_forecasts:
        settings = AppSettings.from_env()
        settings.ensure_local_directories()
        engine = create_database(settings.database_url)
        forecast_store = DataStore(create_session_factory(engine), settings)
    result = replay_focus_day(
        bid_minutes=provider.history(60),
        ask_minutes=provider.history(60, quote_type="ask"),
        five_minutes=provider.history(300),
        hourly=provider.history(3600),
        daily=provider.history(86400),
        selected_date=args.date,
        confirmation_observations=args.confirmation_observations,
        forecast_store=forecast_store,
    )
    berlin = ZoneInfo("Europe/Berlin")
    print(
        f"D-Wave v8 · {result.trading_date:%d.%m.%Y} · "
        f"{result.first_candle_at.astimezone(berlin):%H:%M}–"
        f"{result.last_candle_at.astimezone(berlin):%H:%M} Uhr"
    )
    print(
        f"Depot {result.ending_equity:.2f} EUR · Ergebnis {result.pnl_eur:+.2f} EUR "
        f"({result.pnl_percent:+.2f} %) · vor Kosten {result.gross_before_costs:+.2f} EUR"
    )
    print(
        f"Trades {result.completed_trades} · Gewinner {result.winning_trades} · "
        f"Verlierer {result.losing_trades} · Kosten {result.transaction_costs:.2f} EUR · "
        f"Max. Drawdown {result.max_drawdown_percent:.2f} %"
    )
    print(
        f"Ausgewertete Minuten {result.evaluated_minutes} · übersprungenes Warm-up "
        f"{result.skipped_minutes} · BUY-Minuten {result.buy_signal_minutes} · "
        f"SELL-Minuten {result.sell_signal_minutes} · mittlerer Spread "
        f"{result.average_spread_eur:.3f} EUR"
    )
    print(f"BUY-Bestätigung: {result.confirmation_observations} historische Minutenbeobachtung(en)")
    print(f"Marktbewegung im Datenfenster {result.market_change_percent:+.2f} %")
    if args.save_forecasts:
        print(
            f"Chart-Prognosen: {result.saved_forecasts} neu gespeichert · "
            f"{result.evaluated_forecasts} Zielpunkte erstmals ausgewertet"
        )
    if result.rejected_entries:
        print(
            "Abgelehnte BUY-Minuten: "
            + ", ".join(f"{reason} {count}×" for reason, count in result.rejected_entries)
        )
    if not result.orders:
        print("Keine Orders: Kein Setup hat alle v8-Bedingungen einschließlich Kostenhürde erfüllt.")
    for order in result.orders:
        print(
            f"{order.executed_at.astimezone(berlin):%H:%M} {order.side} "
            f"{order.quantity:.3f} × {order.execution_price:.4f} EUR · "
            f"Kosten {order.costs:.2f} EUR · {order.reason}"
        )
    if any("US-Eröffnungs-Reversal" in order.reason for order in result.orders):
        print(
            "Replay-Hinweis: Die abgeschlossene 15:30-Minutenkerze ersetzt nur im Rückblick "
            "die zwei Live-Prüfungen im Abstand von zehn Sekunden."
        )
    if any("bullischer Mikrotrend" in order.reason for order in result.orders):
        print(
            "Replay-Hinweis: Das abgeschlossene 17:55-Kerzenmuster ersetzt nur im Rückblick "
            "die zwei Live-Prüfungen im Abstand von zehn Sekunden."
        )
    if result.open_position:
        print("Am Ende des Datenfensters ist noch eine Position offen; das Depot ist zum letzten Bid bewertet.")


if __name__ == "__main__":
    main()
