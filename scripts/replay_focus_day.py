"""Fuehrt den v9-Tages-Replay für eine oder alle L&S-Aktien aus."""

from __future__ import annotations

import argparse
from datetime import date
from zoneinfo import ZoneInfo

from src.config import AppSettings
from src.data import ProviderError
from src.database import DataStore, create_database, create_session_factory
from src.focus.analysis import DWAVE_INSTRUMENT
from src.focus.data import resample_ohlcv
from src.focus.replay import replay_focus_day
from src.focus.stock3 import (
    COMPARISON_INSTRUMENTS,
    DWAVE_STOCK3,
    Stock3Instrument,
    Stock3LangSchwarzProvider,
)


def _print_result(name: str, result, *, forecasts_saved: bool) -> None:
    berlin = ZoneInfo("Europe/Berlin")
    print(
        f"{name} · v9 · {result.trading_date:%d.%m.%Y} · "
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
    if forecasts_saved:
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
        print("Keine Replay-Orders: Kein Setup hat alle v9-Bedingungen erfüllt.")
    for order in result.orders:
        print(
            f"{order.executed_at.astimezone(berlin):%H:%M} {order.side} "
            f"{order.quantity:.3f} × {order.execution_price:.4f} EUR · "
            f"Kosten {order.costs:.2f} EUR · {order.reason}"
        )
    print()


def _run_instrument(
    instrument: Stock3Instrument,
    *,
    selected_date: date | None,
    confirmation_observations: int,
    forecast_store: DataStore | None,
):
    provider = Stock3LangSchwarzProvider(instrument=instrument)
    hourly = provider.history(3600)
    try:
        daily = provider.history(86400)
    except ProviderError:
        daily = resample_ohlcv(hourly, "1D", drop_future_label=True)
    symbol = (
        DWAVE_INSTRUMENT.exchange_symbol
        if instrument == DWAVE_STOCK3
        else instrument.isin
    )
    return replay_focus_day(
        bid_minutes=provider.history(60),
        ask_minutes=provider.history(60, quote_type="ask"),
        five_minutes=provider.history(300),
        hourly=hourly,
        daily=daily,
        selected_date=selected_date,
        confirmation_observations=confirmation_observations,
        forecast_store=forecast_store,
        forecast_symbol=symbol,
        forecast_isin=instrument.isin,
        allow_neutral_context=instrument != DWAVE_STOCK3,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="L&S-v9-Tages-Replay")
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
    parser.add_argument(
        "--all-instruments",
        action="store_true",
        help="D-Wave und alle darunter angezeigten Vergleichsaktien durchlaufen",
    )
    args = parser.parse_args()
    forecast_store = None
    if args.save_forecasts:
        settings = AppSettings.from_env()
        settings.ensure_local_directories()
        engine = create_database(settings.database_url)
        forecast_store = DataStore(create_session_factory(engine), settings)
    instruments = (
        (DWAVE_STOCK3, *COMPARISON_INSTRUMENTS)
        if args.all_instruments
        else (DWAVE_STOCK3,)
    )
    failures: list[str] = []
    for instrument in instruments:
        try:
            result = _run_instrument(
                instrument,
                selected_date=args.date,
                confirmation_observations=args.confirmation_observations,
                forecast_store=forecast_store,
            )
        except Exception as exc:
            failures.append(f"{instrument.name}: {exc}")
            print(f"{instrument.name}: FEHLER · {exc}")
            continue
        _print_result(instrument.name, result, forecasts_saved=args.save_forecasts)
    if failures:
        raise SystemExit("Replay unvollständig: " + "; ".join(failures))


if __name__ == "__main__":
    main()
