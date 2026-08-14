"""Fuehrt den heutigen D-Wave-v2-Replay mit historischen L&S-Spreads aus."""

from __future__ import annotations

import argparse
from zoneinfo import ZoneInfo

from src.focus.replay import replay_focus_day
from src.focus.stock3 import Stock3LangSchwarzProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="D-Wave-v2-Tages-Replay")
    parser.add_argument(
        "--confirmation-observations",
        type=int,
        default=2,
        help="Historische Minutenbeobachtungen, die ein BUY bestätigen müssen",
    )
    args = parser.parse_args()
    provider = Stock3LangSchwarzProvider()
    result = replay_focus_day(
        bid_minutes=provider.history(60),
        ask_minutes=provider.history(60, quote_type="ask"),
        five_minutes=provider.history(300),
        hourly=provider.history(3600),
        daily=provider.history(86400),
        confirmation_observations=args.confirmation_observations,
    )
    berlin = ZoneInfo("Europe/Berlin")
    print(
        f"D-Wave v2 · {result.trading_date:%d.%m.%Y} · "
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
    if result.rejected_entries:
        print(
            "Abgelehnte BUY-Minuten: "
            + ", ".join(f"{reason} {count}×" for reason, count in result.rejected_entries)
        )
    if not result.orders:
        print("Keine Orders: Kein Setup hat alle v2-Bedingungen einschließlich Kostenhürde erfüllt.")
    for order in result.orders:
        print(
            f"{order.executed_at.astimezone(berlin):%H:%M} {order.side} "
            f"{order.quantity:.3f} × {order.execution_price:.4f} EUR · "
            f"Kosten {order.costs:.2f} EUR · {order.reason}"
        )
    if result.open_position:
        print("Am Ende des Datenfensters ist noch eine Position offen; das Depot ist zum letzten Bid bewertet.")


if __name__ == "__main__":
    main()
