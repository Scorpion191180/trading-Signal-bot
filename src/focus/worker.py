"""Vom Streamlit-Prozess unabhängiger D-Wave-Papierhandel."""

from __future__ import annotations

import argparse
import fcntl
import logging
import signal as process_signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from time import monotonic
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory

from .analysis import DWAVE_INSTRUMENT, IntradaySignal, analyze_timeframes, build_market_signal
from .data import resample_ohlcv
from .paper import PAPER_STRATEGY_VERSION, PaperAccount, current_paper_account, run_paper_account
from .quote import LiveQuote, resample_intraday_candles
from .stock3 import Stock3LangSchwarzProvider

LOGGER = logging.getLogger(__name__)
BOT_KEY = "dwave-paper"
ACTIVE_POLL_SECONDS = 10
IDLE_POLL_SECONDS = 60
ENTRY_CONFIRMATION_CYCLES = 3
BERLIN = ZoneInfo("Europe/Berlin")
HISTORY_TTL_SECONDS = {60: 10, 300: 60, 3600: 300, 86400: 900}


class MarketProvider(Protocol):
    def quote(self) -> LiveQuote: ...

    def history(self, resolution_seconds: int) -> pd.DataFrame: ...


@dataclass(frozen=True)
class WorkerCycle:
    quote: LiveQuote
    signal: IntradaySignal
    account: PaperAccount


class WorkerWarmup(RuntimeError):
    """Die Quelle ist erreichbar, hat heute aber noch zu wenige Beobachtungen."""


def session_is_active(now: datetime) -> bool:
    local = now.astimezone(BERLIN)
    local_time = local.time().replace(tzinfo=None)
    return local.weekday() < 5 and time(7, 30) <= local_time <= time(23, 0)


def _aware_bucket_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    return timestamp.floor("5min")


def _latest_trading_day(frame: pd.DataFrame, quote: LiveQuote) -> pd.DataFrame:
    local_index = frame.index.tz_convert(BERLIN)
    quote_date = (quote.quoted_at or quote.fetched_at).astimezone(BERLIN).date()
    selected = frame.loc[local_index.date == quote_date].copy()
    if selected.empty:
        selected = frame.loc[local_index.date == local_index[-1].date()].copy()
    selected.attrs.update(frame.attrs)
    if selected.empty:
        return selected

    quote_time = pd.Timestamp(quote.quoted_at or quote.fetched_at).floor("min")
    start = selected.index[0].floor("min")
    end = max(selected.index[-1].floor("min"), quote_time)
    minute_index = pd.date_range(start, end, freq="1min", tz="UTC", name=selected.index.name)
    completed = selected.reindex(minute_index)
    completed["close"] = completed["close"].ffill()
    for column in ("open", "high", "low"):
        completed[column] = completed[column].fillna(completed["close"])
    completed["volume"] = completed["volume"].fillna(0.0)
    live_minute = quote_time if quote_time in completed.index else completed.index[-1]
    previous_close = float(completed["close"].shift(1).loc[live_minute])
    if pd.isna(previous_close):
        previous_close = quote.bid
    completed.loc[live_minute, "open"] = float(completed.loc[live_minute, "open"] or previous_close)
    completed.loc[live_minute, "high"] = max(float(completed.loc[live_minute, "high"]), quote.bid)
    completed.loc[live_minute, "low"] = min(float(completed.loc[live_minute, "low"]), quote.bid)
    completed.loc[live_minute, "close"] = quote.bid
    completed.attrs.update(selected.attrs)
    completed.attrs["filled_unchanged_minutes"] = len(completed) - len(selected)
    return completed


def _completed_candles(frame: pd.DataFrame, resolution_seconds: int, as_of: datetime) -> pd.DataFrame:
    """Entfernt die noch laufende Kerze, damit der Bot nur bestaetigte Schlusskurse handelt."""

    if frame.empty:
        return frame.copy()
    timestamp = pd.Timestamp(as_of)
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    epoch_seconds = int(timestamp.timestamp())
    cutoff_seconds = epoch_seconds - epoch_seconds % resolution_seconds - resolution_seconds
    cutoff = pd.Timestamp(cutoff_seconds, unit="s", tz="UTC")
    completed = frame.loc[frame.index <= cutoff].copy()
    completed.attrs.update(frame.attrs)
    return completed


class FocusPaperWorker:
    """Analysiert L&S im Hintergrund und ist der einzige Schreiber von Papierorders."""

    def __init__(
        self,
        store: DataStore,
        *,
        provider: MarketProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.provider = provider or Stock3LangSchwarzProvider()
        self.clock = clock or (lambda: datetime.now(UTC))
        self._history_cache: dict[int, tuple[float, pd.DataFrame]] = {}
        self._entry_candidate_bucket: str | None = None
        self._entry_candidate_cycles = 0

    def _history(self, resolution_seconds: int) -> pd.DataFrame:
        cached = self._history_cache.get(resolution_seconds)
        ttl = HISTORY_TTL_SECONDS[resolution_seconds]
        if cached is not None and monotonic() - cached[0] < ttl:
            return cached[1].copy()
        frame = self.provider.history(resolution_seconds)
        self._history_cache[resolution_seconds] = (monotonic(), frame.copy())
        return frame

    def _frames(self, quote: LiveQuote) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
        minute = _latest_trading_day(self._history(60), quote)
        signal_at = quote.quoted_at or quote.fetched_at
        five_minutes = _completed_candles(self._history(300), 300, signal_at)
        fifteen_minutes = _completed_candles(
            resample_intraday_candles(five_minutes, 15),
            900,
            signal_at,
        )
        hourly = _completed_candles(self._history(3600), 3600, signal_at)
        daily = _completed_candles(self._history(86400), 86400, signal_at)
        frames = {
            "1m": minute,
            "5m": five_minutes,
            "15m": fifteen_minutes,
            "1h": hourly,
            "1d": daily,
            "1wk": resample_ohlcv(daily, "W-FRI", drop_future_label=True),
            "1mo": resample_ohlcv(daily, "ME", drop_future_label=True),
        }
        return minute, frames

    def _entry_confirmed(self, signal: IntradaySignal, signal_at: datetime) -> bool:
        """Verlangt drei gleiche Messungen innerhalb des neuen Fuenf-Minuten-Blocks."""

        timestamp = _aware_bucket_timestamp(signal_at)
        bucket = timestamp.strftime("%Y%m%dT%H%MZ")
        if signal.action != "BUY":
            self._entry_candidate_bucket = None
            self._entry_candidate_cycles = 0
            return False
        if bucket != self._entry_candidate_bucket:
            self._entry_candidate_bucket = bucket
            self._entry_candidate_cycles = 1
        else:
            self._entry_candidate_cycles += 1
        return self._entry_candidate_cycles >= ENTRY_CONFIRMATION_CYCLES

    def _record_forecast(self, candles: pd.DataFrame, quote: LiveQuote, signal: IntradaySignal) -> None:
        observations = [
            (pd.Timestamp(timestamp).to_pydatetime(), float(price))
            for timestamp, price in candles["close"].items()
        ]
        self.store.evaluate_focus_forecasts(
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
            self.store.record_focus_forecast(
                symbol=DWAVE_INSTRUMENT.exchange_symbol,
                provider=quote.venue,
                forecast_at=quote.quoted_at or quote.fetched_at,
                entry_price=quote.bid,
                bid=quote.bid,
                ask=quote.ask,
                direction=signal.forecast_direction,
                model_score=signal.score,
                forecast_low=signal.forecast_low,
                forecast_high=signal.forecast_high,
                market_regime=signal.market_regime,
                strategy_votes=signal.strategy_votes,
                spread_percent=signal.spread_percent or 0.0,
                model_version=PAPER_STRATEGY_VERSION,
            )

    def pause(self, now: datetime) -> None:
        previous = self.store.get_focus_bot_status(BOT_KEY)
        account = current_paper_account(self.store)
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="PAUSED",
            signal_action=previous.signal_action if previous is not None else "WAIT",
            signal_score=previous.signal_score if previous is not None else 50.0,
            account_state=account.state,
            message="Außerhalb der L&S-Handelszeit 07:30–23:00 Uhr",
            heartbeat_at=now,
        )

    def record_error(self, error: Exception, now: datetime) -> None:
        previous = self.store.get_focus_bot_status(BOT_KEY)
        account = current_paper_account(self.store)
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="ERROR",
            signal_action=previous.signal_action if previous is not None else "WAIT",
            signal_score=previous.signal_score if previous is not None else 50.0,
            account_state=account.state,
            message="Keine Papierorder: Kurs- oder Analysefehler",
            heartbeat_at=now,
            last_error=str(error),
        )

    def record_warmup(self, message: str, now: datetime) -> None:
        previous = self.store.get_focus_bot_status(BOT_KEY)
        account = current_paper_account(self.store)
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="WARMUP",
            signal_action=previous.signal_action if previous is not None else "WAIT",
            signal_score=previous.signal_score if previous is not None else 50.0,
            account_state=account.state,
            message=message,
            heartbeat_at=now,
        )

    def run_once(self, *, force: bool = False) -> WorkerCycle | None:
        now = self.clock()
        if not force and not session_is_active(now):
            self.pause(now)
            return None

        quote = self.provider.quote()
        candles, frames = self._frames(quote)
        analyses, enriched, errors = analyze_timeframes(frames)
        if errors:
            missing = "; ".join(errors.values())
            if all("zu wenige abgeschlossene Kerzen" in message for message in errors.values()):
                raise WorkerWarmup(f"Sicherer Datenaufbau: {missing}")
            raise RuntimeError(f"Multi-Timeframe-Analyse unvollständig: {missing}")
        signal = build_market_signal(
            analyses,
            enriched,
            now=now,
            live_price=quote.bid,
            session_close=time(23, 0),
            spread_percent=quote.spread_percent,
            order_imbalance=None,
            require_volume_confirmation=False,
            enforce_liquidity_filter=False,
        )
        signal_at = quote.quoted_at or quote.fetched_at
        account = run_paper_account(
            self.store,
            quote,
            signal,
            signal_at=signal_at,
            entry_confirmed=self._entry_confirmed(signal, signal_at),
        )
        self._record_forecast(candles, quote, signal)
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="ACTIVE",
            signal_action=signal.action,
            signal_score=signal.score,
            account_state=account.state,
            message=f"L&S geprüft · {signal.headline}",
            heartbeat_at=now,
            quote_at=signal_at,
        )
        return WorkerCycle(quote=quote, signal=signal, account=account)

    def run_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            now = self.clock()
            try:
                cycle = self.run_once()
            except WorkerWarmup as exc:
                self.record_warmup(str(exc), now)
                delay = ACTIVE_POLL_SECONDS
            except Exception as exc:
                LOGGER.exception("Der D-Wave-Papier-Bot konnte den Zyklus nicht abschließen.")
                self.record_error(exc, now)
                delay = ACTIVE_POLL_SECONDS
            else:
                delay = ACTIVE_POLL_SECONDS if cycle is not None else IDLE_POLL_SECONDS
            stop_event.wait(delay)


def _store() -> DataStore:
    settings = AppSettings.from_env()
    settings.ensure_local_directories()
    engine = create_database(settings.database_url)
    return DataStore(create_session_factory(engine), settings)


def _singleton_lock() -> object:
    """Verhindert zwei gleichzeitige Order-Schreiber aus LaunchAgent und Konsole."""

    lock_path = Path("data/dwave-paper-bot.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise SystemExit("Der D-Wave-Hintergrundbot läuft bereits.") from exc
    return handle


def main() -> None:
    parser = argparse.ArgumentParser(description="Unabhängiger D-Wave-Papier-Bot")
    parser.add_argument("--once", action="store_true", help="Genau einen Prüfzyklus ausführen")
    parser.add_argument("--force", action="store_true", help="Daten auch außerhalb der Sitzung prüfen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    singleton = _singleton_lock()
    worker = FocusPaperWorker(_store())
    if args.once:
        try:
            worker.run_once(force=args.force)
        except WorkerWarmup as exc:
            worker.record_warmup(str(exc), worker.clock())
        except Exception as exc:
            worker.record_error(exc, worker.clock())
            raise
        return

    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    process_signal.signal(process_signal.SIGTERM, stop)
    process_signal.signal(process_signal.SIGINT, stop)
    worker.run_forever(stop_event)
    _ = singleton


if __name__ == "__main__":
    main()
