"""Vom Streamlit-Prozess unabhängiger L&S-Mehraktien-Papierhandel."""

from __future__ import annotations

import argparse
import fcntl
import logging
import signal as process_signal
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from pathlib import Path
from time import monotonic
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory

from .analysis import (
    CANDLE_PATTERN_EVENT_PREFIX,
    DWAVE_INSTRUMENT,
    ExternalMarketContext,
    IntradaySignal,
    analyze_timeframes,
    build_market_signal,
)
from .context import FocusContextProvider
from .data import resample_ohlcv
from .paper import PAPER_STRATEGY_VERSION, PaperAccount, current_paper_account, run_paper_account
from .quality import forecast_horizon_payloads, forecast_quality_map
from .quote import LiveQuote, resample_intraday_candles
from .stock3 import COMPARISON_INSTRUMENTS, Stock3Instrument, Stock3LangSchwarzProvider

LOGGER = logging.getLogger(__name__)
BOT_KEY = "dwave-paper"
ACTIVE_POLL_SECONDS = 10
IDLE_POLL_SECONDS = 60
ENTRY_CONFIRMATION_CYCLES = 1
BERLIN = ZoneInfo("Europe/Berlin")
HISTORY_TTL_SECONDS = {60: 10, 300: 60, 3600: 300, 86400: 900}
CONTEXT_TTL_SECONDS = 300
COMPARISON_POLL_SECONDS = 60


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
        context_provider: FocusContextProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        comparison_provider_factory: Callable[[Stock3Instrument], MarketProvider] | None = None,
    ) -> None:
        self.store = store
        self._comparison_enabled = provider is None or comparison_provider_factory is not None
        self.provider = provider or Stock3LangSchwarzProvider()
        self._comparison_provider_factory = comparison_provider_factory or (
            lambda instrument: Stock3LangSchwarzProvider(instrument=instrument)
        )
        self.context_provider = context_provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self._history_cache: dict[int, tuple[float, pd.DataFrame]] = {}
        self._context_cache: tuple[float, ExternalMarketContext] | None = None
        self._entry_candidates: dict[str, tuple[str, int]] = {}
        self._last_comparison_poll = 0.0
        self._last_comparison_count = 0

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

    def _external_context(self) -> ExternalMarketContext | None:
        if self.context_provider is None:
            return None
        if (
            self._context_cache is not None
            and monotonic() - self._context_cache[0] < CONTEXT_TTL_SECONDS
        ):
            return self._context_cache[1]
        context, news_items = self.context_provider.snapshot()
        if news_items:
            self.store.upsert_news(list(news_items))
        self._context_cache = (monotonic(), context)
        return context

    def _entry_confirmed(
        self,
        signal: IntradaySignal,
        signal_at: datetime,
        *,
        symbol: str = DWAVE_INSTRUMENT.exchange_symbol,
    ) -> bool:
        """Bestätigt ein Signal nach einer vollständig ausgewerteten Live-Messung."""

        timestamp = _aware_bucket_timestamp(signal_at)
        bucket = timestamp.strftime("%Y%m%dT%H%MZ")
        normalized_symbol = symbol.upper().strip()
        if signal.action != "BUY":
            self._entry_candidates.pop(normalized_symbol, None)
            return False
        if signal.structure_event.startswith(CANDLE_PATTERN_EVENT_PREFIX):
            self._entry_candidates.pop(normalized_symbol, None)
            return True
        previous_bucket, previous_cycles = self._entry_candidates.get(
            normalized_symbol,
            ("", 0),
        )
        if bucket != previous_bucket:
            cycles = 1
        else:
            cycles = previous_cycles + 1
        self._entry_candidates[normalized_symbol] = (bucket, cycles)
        return cycles >= ENTRY_CONFIRMATION_CYCLES

    def _record_forecast(
        self,
        candles: pd.DataFrame,
        quote: LiveQuote,
        signal: IntradaySignal,
        *,
        symbol: str = DWAVE_INSTRUMENT.exchange_symbol,
    ) -> None:
        observations = [
            (pd.Timestamp(timestamp).to_pydatetime(), float(price))
            for timestamp, price in candles["close"].items()
        ]
        self.store.evaluate_focus_forecasts(
            symbol,
            observations,
            provider=quote.venue,
        )
        if (
            signal.market_open
            and signal.data_age_minutes <= 4
            and signal.forecast_low is not None
            and signal.forecast_high is not None
        ):
            quality = forecast_quality_map(
                self.store,
                PAPER_STRATEGY_VERSION,
                symbol=symbol,
            )
            self.store.record_focus_forecast(
                symbol=symbol,
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
                horizon_forecasts=forecast_horizon_payloads(signal, quality),
                model_version=PAPER_STRATEGY_VERSION,
            )

    @staticmethod
    def _comparison_frames(
        provider: Stock3LangSchwarzProvider,
        quote: LiveQuote,
    ) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
        signal_at = quote.quoted_at or quote.fetched_at
        minute = _latest_trading_day(provider.history(60), quote)
        five_minutes = _completed_candles(provider.history(300), 300, signal_at)
        fifteen_minutes = _completed_candles(
            resample_intraday_candles(five_minutes, 15),
            900,
            signal_at,
        )
        hourly = _completed_candles(provider.history(3600), 3600, signal_at)
        try:
            daily_history = provider.history(86400)
        except Exception:
            daily_history = resample_ohlcv(hourly, "1D", drop_future_label=True)
        daily = _completed_candles(daily_history, 86400, signal_at)
        return minute, {
            "1m": minute,
            "5m": five_minutes,
            "15m": fifteen_minutes,
            "1h": hourly,
            "1d": daily,
            "1wk": resample_ohlcv(daily, "W-FRI", drop_future_label=True),
            "1mo": resample_ohlcv(daily, "ME", drop_future_label=True),
        }

    def _process_comparison_assets(self, now: datetime) -> int:
        """Misst und handelt jede weitere Aktie unabhängig im gemeinsamen Papierdepot."""

        if not self._comparison_enabled:
            return 0
        current_tick = monotonic()
        if current_tick - self._last_comparison_poll < COMPARISON_POLL_SECONDS:
            return self._last_comparison_count
        self._last_comparison_poll = current_tick
        processed = 0
        for instrument in COMPARISON_INSTRUMENTS:
            try:
                provider = self._comparison_provider_factory(instrument)
                quote = provider.quote()
                candles, frames = self._comparison_frames(provider, quote)
                analyses, enriched, errors = analyze_timeframes(
                    frames,
                    allow_neutral_long_term_context=True,
                )
                if errors:
                    raise RuntimeError("; ".join(errors.values()))
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
                run_paper_account(
                    self.store,
                    quote,
                    signal,
                    signal_at=signal_at,
                    entry_confirmed=self._entry_confirmed(
                        signal,
                        signal_at,
                        symbol=instrument.isin,
                    ),
                    symbol=instrument.isin,
                )
                self._record_forecast(
                    candles,
                    quote,
                    signal,
                    symbol=instrument.isin,
                )
                processed += 1
            except Exception as exc:
                LOGGER.warning("Papierzyklus für %s fehlgeschlagen: %s", instrument.name, exc)
        self._last_comparison_count = processed
        return processed

    def _bot_enabled(self) -> bool:
        account = current_paper_account(self.store)
        return bool(self.store.get_portfolio(account.portfolio_id).active)

    def record_disabled(self, now: datetime) -> None:
        previous = self.store.get_focus_bot_status(BOT_KEY)
        account = current_paper_account(self.store)
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="DISABLED",
            signal_action=previous.signal_action if previous is not None else "WAIT",
            signal_score=previous.signal_score if previous is not None else 50.0,
            account_state=account.state,
            message="Vom Benutzer ausgeschaltet · keine automatischen Orders",
            heartbeat_at=now,
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
        if not self._bot_enabled():
            self.record_disabled(now)
            return None
        if not force and not session_is_active(now):
            self.pause(now)
            return None

        comparison_count = self._process_comparison_assets(now)
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
            external_context=self._external_context(),
        )
        signal_at = quote.quoted_at or quote.fetched_at
        account = run_paper_account(
            self.store,
            quote,
            signal,
            signal_at=signal_at,
            entry_confirmed=self._entry_confirmed(
                signal,
                signal_at,
                symbol=DWAVE_INSTRUMENT.exchange_symbol,
            ),
        )
        self._record_forecast(candles, quote, signal)
        refreshed_account = current_paper_account(self.store, quote.bid)
        account = (
            replace(refreshed_account, state=account.state)
            if refreshed_account.open_positions == 0 and account.state != "CASH"
            else refreshed_account
        )
        self.store.update_focus_bot_status(
            bot_key=BOT_KEY,
            run_state="ACTIVE",
            signal_action=signal.action,
            signal_score=signal.score,
            account_state=account.state,
            message=(
                f"L&S geprüft · D-Wave {signal.headline} · "
                f"{comparison_count}/{len(COMPARISON_INSTRUMENTS)} weitere Aktien zuletzt geprüft"
            ),
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
                LOGGER.exception("Der Mehraktien-Papier-Bot konnte den Zyklus nicht abschließen.")
                self.record_error(exc, now)
                delay = ACTIVE_POLL_SECONDS
            else:
                delay = ACTIVE_POLL_SECONDS if cycle is not None or not self._bot_enabled() else IDLE_POLL_SECONDS
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
    parser = argparse.ArgumentParser(description="Unabhängiger L&S-Mehraktien-Papier-Bot")
    parser.add_argument("--once", action="store_true", help="Genau einen Prüfzyklus ausführen")
    parser.add_argument("--force", action="store_true", help="Daten auch außerhalb der Sitzung prüfen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    singleton = _singleton_lock()
    worker = FocusPaperWorker(_store(), context_provider=FocusContextProvider())
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
