"""Erklärbare Multi-Timeframe-Logik für sehr kurze D-Wave-Trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.analysis.indicators import atr, ema, rsi


@dataclass(frozen=True)
class Instrument:
    name: str
    yahoo_symbol: str
    exchange_symbol: str
    isin: str
    wkn: str
    venue: str
    currency: str


DWAVE_INSTRUMENT = Instrument(
    name="D-Wave Quantum Inc.",
    yahoo_symbol="RQ0.F",
    exchange_symbol="RQ0",
    isin="US26740W1099",
    wkn="A3DSV9",
    venue="Deutscher Markt",
    currency="EUR",
)


@dataclass(frozen=True)
class TimeframeSpec:
    key: str
    label: str
    fast_ema: int
    slow_ema: int
    chart_rows: int


TIMEFRAME_SPECS = (
    TimeframeSpec("1m", "1 Minute", 8, 21, 180),
    TimeframeSpec("5m", "5 Minuten", 8, 21, 180),
    TimeframeSpec("15m", "15 Minuten", 8, 21, 160),
    TimeframeSpec("1h", "1 Stunde", 10, 30, 160),
    TimeframeSpec("1d", "Tageschart", 20, 50, 220),
    TimeframeSpec("1wk", "Wochenchart", 10, 30, 180),
    TimeframeSpec("1mo", "Monatschart", 6, 18, 100),
)
SPEC_BY_KEY = {spec.key: spec for spec in TIMEFRAME_SPECS}
BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
US_OPENING_REVERSAL_EVENT = "US-Eröffnung: Abverkauf und Rückeroberung des vorherigen Tiefs"
MICROTREND_CONTINUATION_EVENT = "Mikrotrend: steigende grüne Kerzen und lokaler Ausbruch"
PROFIT_EXHAUSTION_EVENT = "Gewinnmitnahme: überkaufter Mikrotrend verliert Schwung"
ADAPTIVE_HOLDING_PERIOD = "adaptiv · meist 5–30 Minuten, maximal 120 Minuten"


@dataclass(frozen=True)
class TimeframeAnalysis:
    key: str
    label: str
    score: float
    trend: str
    setup: str
    price: float
    rsi: float
    relative_volume: float | None
    data_timestamp: datetime
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FocusPosition:
    invested: bool = False
    average_price: float | None = None
    quantity: float | None = None


@dataclass(frozen=True)
class ExternalMarketContext:
    """Vorsichtiger Zusatzkontext aus Märkten und zeitnahen Nachrichten."""

    score: float = 50.0
    market_score: float = 50.0
    news_score: float = 0.5
    reasons: tuple[str, ...] = ()
    headlines: tuple[str, ...] = ()
    updated_at: datetime | None = None
    available: bool = False


@dataclass(frozen=True)
class IntradaySignal:
    action: str
    headline: str
    score: float
    strength: str
    color: str
    current_price: float
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    target: float | None
    holding_period: str
    reasons: tuple[str, ...]
    warning: str
    data_age_minutes: float
    market_open: bool
    forecast_direction: str = "UNENTSCHIEDEN"
    forecast_low: float | None = None
    forecast_high: float | None = None
    market_regime: str = "unklar"
    strategy_votes: tuple[str, ...] = ()
    spread_percent: float | None = None
    trend_forecasts: tuple[TrendForecast, ...] = ()
    demand_low: float | None = None
    demand_high: float | None = None
    liquidity_low: float | None = None
    liquidity_high: float | None = None
    structure_event: str = ""
    external_context_score: float = 50.0
    external_context_reasons: tuple[str, ...] = ()
    latest_news: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrendForecast:
    """Probabilistische Kurszone fuer einen festen Vorwaertshorizont."""

    minutes: int
    direction: str
    expected_price: float
    expected_low: float
    expected_high: float
    confidence: float


@dataclass(frozen=True)
class StrategyEnsemble:
    """Gemeinsame 5–120-Minuten-Einschätzung mehrerer unabhängiger Ansätze."""

    score: float
    direction: str
    expected_low: float
    expected_high: float
    regime: str
    votes: tuple[str, ...]
    positive_votes: int
    negative_votes: int
    horizons: tuple[TrendForecast, ...]


@dataclass(frozen=True)
class SmartMoneyContext:
    """Messbare Teilmenge der SMC-Bilder ohne nachtraeglich subjektives Einzeichnen."""

    bullish_reversal: bool
    bearish_reversal: bool
    demand_retest: bool
    demand_low: float | None
    demand_high: float | None
    liquidity_low: float | None
    liquidity_high: float | None
    event: str


@dataclass(frozen=True)
class OpeningReversal:
    """Zeitlich begrenztes Reversal nach einem Sell-Side-Sweep zur US-Eröffnung."""

    active: bool = False
    event_at: datetime | None = None
    event_low: float | None = None
    reclaimed_level: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    event: str = "Kein bestätigtes US-Eröffnungs-Reversal"


@dataclass(frozen=True)
class MicrotrendContinuation:
    """Frühe Fortsetzung nach Rücksetzer und bullischer Kerzentreppe."""

    active: bool = False
    event_at: datetime | None = None
    breakout_level: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    event: str = "Kein bestätigter Mikrotrend-Ausbruch"


def _rolling_linear_regression(series: pd.Series, length: int = 11) -> pd.Series:
    """Letzter Wert einer rollenden linearen Regression ohne Blick in die Zukunft."""

    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    if len(values) < length:
        return pd.Series(result, index=series.index)
    x_values = np.arange(length, dtype=float)
    sum_x = float(x_values.sum())
    sum_x_squared = float(np.square(x_values).sum())
    denominator = length * sum_x_squared - sum_x**2
    rolling_sum = np.convolve(values, np.ones(length), mode="valid")
    rolling_weighted_sum = np.convolve(values, x_values[::-1], mode="valid")
    slopes = (length * rolling_weighted_sum - sum_x * rolling_sum) / denominator
    means = rolling_sum / length
    projected = means + slopes * ((length - 1) - sum_x / length)
    result[length - 1 :] = projected
    return pd.Series(result, index=series.index)


def _atr_trailing_stop(close: pd.Series, atr_values: pd.Series, multiplier: float = 2.0) -> pd.Series:
    """UT-Bot-inspirierter ATR-Trailing-Stop auf normalen Schlusskursen."""

    stops = np.full(len(close), np.nan, dtype=float)
    values = close.to_numpy(dtype=float)
    losses = (atr_values * multiplier).to_numpy(dtype=float)
    for index, current in enumerate(values):
        loss = losses[index]
        if not np.isfinite(current) or not np.isfinite(loss) or loss <= 0:
            continue
        if index == 0 or not np.isfinite(stops[index - 1]):
            stops[index] = current - loss
            continue
        previous_stop = stops[index - 1]
        previous_close = values[index - 1]
        if current > previous_stop and previous_close > previous_stop:
            stops[index] = max(previous_stop, current - loss)
        elif current < previous_stop and previous_close < previous_stop:
            stops[index] = min(previous_stop, current + loss)
        elif current > previous_stop:
            stops[index] = current - loss
        else:
            stops[index] = current + loss
    return pd.Series(stops, index=close.index)


def _ott_line(support: pd.Series, percent: float = 1.4) -> pd.Series:
    """OTT/MOST-Trendlinie entsprechend dem im Video sichtbaren 1,4-%-Abstand."""

    values = support.to_numpy(dtype=float)
    long_stop = np.full(len(values), np.nan, dtype=float)
    short_stop = np.full(len(values), np.nan, dtype=float)
    direction = np.ones(len(values), dtype=float)
    ott = np.full(len(values), np.nan, dtype=float)
    ratio = percent / 100.0
    for index, current in enumerate(values):
        if not np.isfinite(current):
            continue
        raw_long = current * (1 - ratio)
        raw_short = current * (1 + ratio)
        if index == 0 or not np.isfinite(long_stop[index - 1]):
            long_stop[index] = raw_long
            short_stop[index] = raw_short
        else:
            previous_support = values[index - 1]
            previous_long = long_stop[index - 1]
            previous_short = short_stop[index - 1]
            long_stop[index] = max(raw_long, previous_long) if previous_support > previous_long else raw_long
            short_stop[index] = min(raw_short, previous_short) if previous_support < previous_short else raw_short
            if direction[index - 1] < 0 and current > previous_short:
                direction[index] = 1
            elif direction[index - 1] > 0 and current < previous_long:
                direction[index] = -1
            else:
                direction[index] = direction[index - 1]
        active_stop = long_stop[index] if direction[index] > 0 else short_stop[index]
        ott[index] = active_stop * (1 + ratio / 2) if current > active_stop else active_stop * (1 - ratio / 2)
    return pd.Series(ott, index=support.index)


def add_focus_indicators(frame: pd.DataFrame, spec: TimeframeSpec) -> pd.DataFrame:
    data = frame.copy()
    data["ema_fast"] = ema(data["close"], spec.fast_ema)
    data["ema_slow"] = ema(data["close"], spec.slow_ema)
    data["ema_200"] = ema(data["close"], 200) if len(data) >= 200 else np.nan
    data["rsi_14"] = rsi(data["close"], 14)
    data["macd"] = ema(data["close"], 12) - ema(data["close"], 26)
    data["macd_signal"] = ema(data["macd"], 9)
    data["macd_hist"] = data["macd"] - data["macd_signal"]
    data["atr_14"] = atr(data, 14)
    data["linreg_open"] = _rolling_linear_regression(data["open"])
    data["linreg_close"] = _rolling_linear_regression(data["close"])
    data["linreg_slope"] = data["linreg_close"].diff(3) / 3
    data["ut_stop"] = _atr_trailing_stop(data["close"], data["atr_14"])
    data["ott_support"] = ema(data["close"], 7)
    data["ott"] = _ott_line(data["ott_support"])
    data["previous_high_20"] = data["high"].shift(1).rolling(20, min_periods=10).max()
    data["previous_low_20"] = data["low"].shift(1).rolling(20, min_periods=10).min()
    data["swing_high_12"] = data["high"].shift(1).rolling(12, min_periods=6).max()
    data["swing_low_12"] = data["low"].shift(1).rolling(12, min_periods=6).min()
    sweep_tolerance = data["atr_14"] * 0.05
    data["bullish_liquidity_sweep"] = (
        (data["low"] < data["swing_low_12"] - sweep_tolerance)
        & (data["close"] > data["swing_low_12"])
    )
    data["bearish_liquidity_sweep"] = (
        (data["high"] > data["swing_high_12"] + sweep_tolerance)
        & (data["close"] < data["swing_high_12"])
    )
    candle_body = data["close"] - data["open"]
    data["bullish_displacement"] = (
        (candle_body > data["atr_14"] * 0.90)
        & (data["close"] > data["swing_high_12"])
    )
    data["bearish_displacement"] = (
        (-candle_body > data["atr_14"] * 0.90)
        & (data["close"] < data["swing_low_12"])
    )
    average_volume = data["volume"].shift(1).rolling(20, min_periods=5).mean()
    data["relative_volume"] = data["volume"] / average_volume.replace(0.0, np.nan)
    return data


def _smart_money_context(frame: pd.DataFrame) -> SmartMoneyContext:
    recent_start = max(len(frame) - 10, 0)
    bullish_reversal = False
    bearish_reversal = False
    for sweep_index in np.flatnonzero(frame["bullish_liquidity_sweep"].fillna(False).to_numpy()):
        if sweep_index < recent_start:
            continue
        confirmation = frame.iloc[sweep_index + 1 :]
        prior_high = float(frame["high"].iloc[max(0, sweep_index - 6) : sweep_index].max())
        if not confirmation.empty and (
            confirmation["bullish_displacement"].any()
            or float(confirmation["close"].max()) > prior_high
        ):
            bullish_reversal = True
    for sweep_index in np.flatnonzero(frame["bearish_liquidity_sweep"].fillna(False).to_numpy()):
        if sweep_index < recent_start:
            continue
        confirmation = frame.iloc[sweep_index + 1 :]
        prior_low = float(frame["low"].iloc[max(0, sweep_index - 6) : sweep_index].min())
        if not confirmation.empty and (
            confirmation["bearish_displacement"].any()
            or float(confirmation["close"].min()) < prior_low
        ):
            bearish_reversal = True

    demand_low: float | None = None
    demand_high: float | None = None
    displacement_indices = np.flatnonzero(frame["bullish_displacement"].fillna(False).to_numpy())
    for displacement_index in reversed(displacement_indices[-6:]):
        search_start = max(displacement_index - 4, 0)
        origin_index = displacement_index - 1
        for candidate in range(displacement_index - 1, search_start - 1, -1):
            candle = frame.iloc[candidate]
            if float(candle["close"]) < float(candle["open"]):
                origin_index = candidate
                break
        origin = frame.iloc[origin_index]
        candidate_low = float(origin["low"])
        candidate_high = max(float(origin["open"]), float(origin["close"]))
        following_closes = frame["close"].iloc[origin_index + 1 :]
        if not following_closes.empty and float(following_closes.min()) >= candidate_low:
            demand_low, demand_high = candidate_low, candidate_high
            break

    latest = frame.iloc[-1]
    demand_retest = bool(
        demand_low is not None
        and demand_high is not None
        and float(latest["low"]) <= demand_high * 1.002
        and float(latest["close"]) >= demand_high
        and float(latest["close"]) > float(latest["open"])
    )
    if bullish_reversal:
        event = "Sell-Side-Liquidität geholt · bullischer Strukturwechsel"
    elif bearish_reversal:
        event = "Buy-Side-Liquidität geholt · bärischer Strukturwechsel"
    elif demand_retest:
        event = "Bestätigter Retest der Nachfragezone"
    else:
        event = "Kein bestätigter Sweep-Strukturwechsel"
    return SmartMoneyContext(
        bullish_reversal=bullish_reversal,
        bearish_reversal=bearish_reversal,
        demand_retest=demand_retest,
        demand_low=demand_low,
        demand_high=demand_high,
        liquidity_low=float(latest["swing_low_12"]) if np.isfinite(latest["swing_low_12"]) else None,
        liquidity_high=float(latest["swing_high_12"]) if np.isfinite(latest["swing_high_12"]) else None,
        event=event,
    )


def _us_opening_reversal(
    frame: pd.DataFrame,
    now: datetime,
    spread_percent: float | None,
) -> OpeningReversal:
    """Erkennt einen Abverkauf mit sofortiger Rückeroberung rund um 09:30 New York.

    Die Uhrzeit wird aus der New-York-Zeitzone abgeleitet, damit die zwei Wochen mit
    abweichender Sommerzeit zwischen Europa und den USA korrekt behandelt werden.
    Nur abgeschlossene beziehungsweise aktuell beobachtete Kerzen bis ``now`` werden
    ausgewertet; spätere Tagesdaten fließen nicht ein.
    """

    if frame.empty or len(frame) < 32 or (spread_percent is not None and spread_percent > 0.45):
        return OpeningReversal()

    current_time = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    current_time = current_time.astimezone(UTC)
    new_york_date = current_time.astimezone(NEW_YORK).date()
    us_open = datetime.combine(new_york_date, time(9, 30), tzinfo=NEW_YORK).astimezone(UTC)
    if not us_open <= current_time <= us_open + timedelta(minutes=8):
        return OpeningReversal()

    data = frame.copy()
    index = pd.DatetimeIndex(data.index)
    index = index.tz_localize(UTC) if index.tz is None else index.tz_convert(UTC)
    data.index = index
    data = data.loc[data.index <= pd.Timestamp(current_time)]
    candidate_window = data.loc[
        (data.index >= pd.Timestamp(us_open))
        & (data.index <= pd.Timestamp(us_open + timedelta(minutes=2)))
    ]
    if candidate_window.empty:
        return OpeningReversal()

    latest = data.iloc[-1]
    latest_close = float(latest["close"])
    latest_low = float(latest["low"])
    for candidate_at, candidate in reversed(list(candidate_window.iterrows())):
        prior = data.loc[data.index < candidate_at].tail(30)
        if len(prior) < 20:
            continue
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        candle_open = float(candidate["open"])
        candle_high = float(candidate["high"])
        candle_low = float(candidate["low"])
        candle_close = float(candidate["close"])
        candle_range = candle_high - candle_low
        candidate_atr = float(candidate.get("atr_14", np.nan))
        if not np.isfinite(candidate_atr) or candidate_atr <= 0:
            candidate_atr = max(candle_range, candle_close * 0.002)
        drop_from_prior_high = (prior_high - candle_low) / prior_high if prior_high > 0 else 0.0
        swept_distance = prior_low - candle_low
        close_position = (candle_close - candle_low) / candle_range if candle_range > 0 else 0.0
        reclaimed = (
            drop_from_prior_high >= 0.012
            and swept_distance >= max(candidate_atr * 0.05, prior_low * 0.0002)
            and candle_close > prior_low
            and candle_close - candle_open >= candidate_atr * 0.25
            and close_position >= 0.70
        )
        still_valid = (
            latest_close >= candle_close
            and latest_low >= candle_low
            and latest_close <= candle_close + candidate_atr * 4.0
        )
        if not reclaimed or not still_valid:
            continue

        stop_loss = prior_low - candidate_atr * 0.12
        risk_distance = candle_close - stop_loss
        if risk_distance <= 0:
            continue
        return OpeningReversal(
            active=True,
            event_at=pd.Timestamp(candidate_at).to_pydatetime(),
            event_low=candle_low,
            reclaimed_level=prior_low,
            stop_loss=stop_loss,
            target=candle_close + risk_distance * 3.0,
            event=US_OPENING_REVERSAL_EVENT,
        )
    return OpeningReversal()


def _microtrend_continuation(
    frame: pd.DataFrame,
    spread_percent: float | None,
) -> MicrotrendContinuation:
    """Erkennt eine kleine bullische Kerzentreppe nach einem echten Rücksetzer."""

    if frame.empty or len(frame) < 24 or (spread_percent is not None and spread_percent > 0.45):
        return MicrotrendContinuation()
    latest = frame.iloc[-1]
    candidate_atr = float(latest.get("atr_14", np.nan))
    if not np.isfinite(candidate_atr) or candidate_atr <= 0:
        return MicrotrendContinuation()

    staircase = frame.tail(4)
    prelude = frame.iloc[-16:-4]
    if len(staircase) < 4 or len(prelude) < 8:
        return MicrotrendContinuation()
    opens = staircase["open"].to_numpy(dtype=float)
    closes = staircase["close"].to_numpy(dtype=float)
    lows = staircase["low"].to_numpy(dtype=float)
    bullish_staircase = bool(
        np.all(closes > opens)
        and np.all(np.diff(closes) >= -candidate_atr * 0.05)
        and np.all(np.diff(lows) > 0)
        and closes[-1] - opens[0] >= candidate_atr * 1.5
    )

    prior_local_high = float(frame["high"].iloc[-12:-1].max())
    breakout = closes[-1] > prior_local_high
    running_high = prelude["high"].cummax()
    pullback_range = float((running_high - prelude["low"]).max())
    preceding_pullback = pullback_range >= candidate_atr * 1.5
    trend_ok = (
        closes[-1] > float(latest["ema_fast"]) > float(latest["ema_slow"])
        and 50 <= float(latest["rsi_14"]) <= 70
    )
    if not (bullish_staircase and breakout and preceding_pullback and trend_ok):
        return MicrotrendContinuation()

    stop_reference = min(float(staircase["low"].min()), prior_local_high)
    stop_loss = stop_reference - candidate_atr * 0.25
    risk_distance = closes[-1] - stop_loss
    return MicrotrendContinuation(
        active=True,
        event_at=pd.Timestamp(frame.index[-1]).to_pydatetime(),
        breakout_level=prior_local_high,
        stop_loss=stop_loss,
        target=closes[-1] + max(risk_distance * 2.2, candidate_atr * 4.0, pullback_range * 1.5),
        event=MICROTREND_CONTINUATION_EVENT,
    )


def _profit_exhaustion(frame: pd.DataFrame) -> bool:
    """Erkennt die erste deutliche rote Reaktion nach extremem 1-Minuten-RSI."""

    if len(frame) < 5:
        return False
    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    candidate_atr = float(latest.get("atr_14", np.nan))
    if not np.isfinite(candidate_atr) or candidate_atr <= 0:
        return False
    prior_peak_rsi = float(frame["rsi_14"].iloc[-4:-1].max())
    latest_rsi = float(latest["rsi_14"])
    recent_high = float(frame["high"].iloc[-4:].max())
    return bool(
        prior_peak_rsi >= 80
        and prior_peak_rsi - latest_rsi >= 5
        and float(latest["close"]) < float(latest["open"])
        and float(latest["close"]) < float(previous["close"])
        and recent_high - float(latest["close"]) >= candidate_atr * 0.25
    )


def _momentum_factor(current_rsi: float, macd_hist: float, previous_hist: float) -> float:
    if 52 <= current_rsi <= 68:
        rsi_factor = 1.0
    elif 45 <= current_rsi < 52 or 68 < current_rsi <= 73:
        rsi_factor = 0.55
    elif current_rsi > 78 or current_rsi < 35:
        rsi_factor = 0.05
    else:
        rsi_factor = 0.3
    macd_factor = 1.0 if macd_hist > 0 and macd_hist >= previous_hist else 0.6 if macd_hist > 0 else 0.15
    return (rsi_factor * 0.55) + (macd_factor * 0.45)


def analyze_timeframe(frame: pd.DataFrame, spec: TimeframeSpec) -> tuple[TimeframeAnalysis, pd.DataFrame]:
    if len(frame) < max(spec.slow_ema + 10, 35):
        raise ValueError(f"{spec.label}: zu wenige abgeschlossene Kerzen ({len(frame)}).")
    # Fuer das aktuelle Signal reichen 800 vergangene Kerzen selbst fuer EMA 200
    # mit grossem Warm-up. Die ungekappte Historie bleibt separat fuer den Chart erhalten.
    data = add_focus_indicators(frame.tail(800), spec)
    latest = data.iloc[-1]
    previous = data.iloc[-2]
    close = float(latest["close"])
    fast = float(latest["ema_fast"])
    slow = float(latest["ema_slow"])
    current_rsi = float(latest["rsi_14"])
    macd_hist = float(latest["macd_hist"])
    previous_hist = float(previous["macd_hist"])
    long_reference = latest["ema_200"]
    if pd.isna(long_reference):
        lookback = min(20, len(data) - 1)
        long_condition = close > float(data["close"].iloc[-1 - lookback])
    else:
        long_condition = close > float(long_reference)

    trend_checks = (
        close > fast,
        fast > slow,
        fast > float(data["ema_fast"].iloc[-4]),
        long_condition,
    )
    trend_factor = sum(trend_checks) / len(trend_checks)
    momentum_factor = _momentum_factor(current_rsi, macd_hist, previous_hist)
    previous_high = float(latest["previous_high_20"])
    previous_low = float(latest["previous_low_20"])
    bullish_candle = close > float(latest["open"])
    breakout = close > previous_high
    pullback = close > fast and float(latest["low"]) <= fast * 1.006 and bullish_candle
    if breakout:
        structure_factor, setup = 1.0, "Ausbruch"
    elif pullback:
        structure_factor, setup = 0.8, "Trend-Rücksetzer"
    elif close > (previous_high + previous_low) / 2:
        structure_factor, setup = 0.55, "obere Handelsspanne"
    else:
        structure_factor, setup = 0.2, "schwache Struktur"
    relative_volume_value = latest["relative_volume"]
    if pd.isna(relative_volume_value) or float(relative_volume_value) <= 0:
        volume_factor = 0.5
        relative_volume = None
    else:
        relative_volume = float(relative_volume_value)
        volume_factor = 1.0 if relative_volume >= 1.4 else 0.7 if relative_volume >= 0.9 else 0.3

    score = round(
        (trend_factor * 45) + (momentum_factor * 25) + (structure_factor * 20) + (volume_factor * 10),
        1,
    )
    trend = "Aufwärts" if score >= 62 else "Abwärts" if score <= 40 else "Seitwärts"
    reasons: list[str] = []
    warnings: list[str] = []
    reasons.append("Kurs über schneller und langsamer EMA" if close > fast > slow else "EMA-Trend noch nicht vollständig positiv")
    reasons.append(f"RSI {current_rsi:.0f} · Momentum {'positiv' if macd_hist > 0 else 'negativ'}")
    reasons.append(f"Chartstruktur: {setup}")
    if relative_volume is None:
        warnings.append("Volumenbestätigung für die jüngste Kerze fehlt")
    elif relative_volume < 0.7:
        warnings.append(f"geringes relatives Volumen ({relative_volume:.2f})")
    if current_rsi > 73:
        warnings.append("kurzfristig überkauft – Einstieg nicht hinterherlaufen")
    timestamp = pd.Timestamp(data.index[-1]).to_pydatetime()
    return (
        TimeframeAnalysis(
            key=spec.key,
            label=spec.label,
            score=score,
            trend=trend,
            setup=setup,
            price=close,
            rsi=current_rsi,
            relative_volume=relative_volume,
            data_timestamp=timestamp,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        ),
        data,
    )


def analyze_timeframes(
    frames: dict[str, pd.DataFrame],
    *,
    allow_neutral_long_term_context: bool = False,
) -> tuple[dict[str, TimeframeAnalysis], dict[str, pd.DataFrame], dict[str, str]]:
    analyses: dict[str, TimeframeAnalysis] = {}
    enriched: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for spec in TIMEFRAME_SPECS:
        frame = frames.get(spec.key)
        if frame is None or frame.empty:
            errors[spec.key] = f"{spec.label}: keine Daten verfügbar."
            continue
        try:
            analyses[spec.key], enriched[spec.key] = analyze_timeframe(frame, spec)
        except (ValueError, IndexError) as exc:
            neutral_minimum = {"1d": 35, "1wk": 8, "1mo": 2}.get(spec.key)
            if (
                allow_neutral_long_term_context
                and neutral_minimum is not None
                and len(frame) >= neutral_minimum
            ):
                context_name = {
                    "1d": "Tages",
                    "1wk": "Wochen",
                    "1mo": "Monats",
                }[spec.key]
                neutral_frame = add_focus_indicators(frame.tail(800), spec)
                analyses[spec.key] = TimeframeAnalysis(
                    key=spec.key,
                    label=spec.label,
                    score=50.0,
                    trend="Seitwärts",
                    setup="noch zu kurze L&S-Historie",
                    price=float(frame["close"].iloc[-1]),
                    rsi=50.0,
                    relative_volume=None,
                    data_timestamp=pd.Timestamp(neutral_frame.index[-1]).to_pydatetime(),
                    reasons=(
                        f"{context_name}kontext bleibt bis zu genügend vollständigen "
                        f"{context_name.lower()}kerzen neutral.",
                    ),
                    warnings=(
                        f"Für diesen Handelsplatz ist die {context_name}historie noch zu kurz.",
                    ),
                )
                enriched[spec.key] = neutral_frame
                continue
            errors[spec.key] = str(exc)
    return analyses, enriched, errors


def _is_german_market_open(now: datetime, session_close: time) -> bool:
    berlin = now.astimezone(BERLIN)
    return berlin.weekday() < 5 and time(7, 30) <= berlin.time().replace(tzinfo=None) <= session_close


def _signal_strength(score: float) -> str:
    return "stark" if score >= 72 or score <= 28 else "moderat" if score >= 62 or score <= 40 else "schwach"


def _bounded_score(value: float) -> float:
    return float(min(max(value, 0.0), 100.0))


def _latest_finite(frame: pd.DataFrame, column: str, fallback: float) -> float:
    value = frame[column].iloc[-1]
    return float(value) if np.isfinite(value) else fallback


def _momentum_strategy(enriched: dict[str, pd.DataFrame], analyses: dict[str, TimeframeAnalysis]) -> float:
    components: list[float] = []
    for key in ("1m", "5m"):
        frame = enriched[key]
        rsi_value = analyses[key].rsi
        rsi_score = _bounded_score(50 + (rsi_value - 50) * 1.2)
        histogram = _latest_finite(frame, "macd_hist", 0.0)
        previous_histogram = float(frame["macd_hist"].iloc[-2])
        if histogram > 0 and histogram >= previous_histogram:
            macd_score = 78.0
        elif histogram > 0:
            macd_score = 62.0
        elif histogram < 0 and histogram <= previous_histogram:
            macd_score = 22.0
        else:
            macd_score = 38.0
        components.append((rsi_score * 0.45) + (macd_score * 0.55))
    return sum(components) / len(components)


def _breakout_strategy(enriched: dict[str, pd.DataFrame], analyses: dict[str, TimeframeAnalysis]) -> float:
    components: list[float] = []
    for key in ("1m", "5m"):
        latest = enriched[key].iloc[-1]
        close = float(latest["close"])
        previous_high = float(latest["previous_high_20"])
        previous_low = float(latest["previous_low_20"])
        relative_volume = analyses[key].relative_volume or 0.0
        if close > previous_high:
            score = 88.0 if relative_volume >= 1.0 else 72.0
        elif close < previous_low:
            score = 12.0 if relative_volume >= 1.0 else 28.0
        elif previous_high > previous_low:
            location = (close - previous_low) / (previous_high - previous_low)
            score = 20 + 60 * location
        else:
            score = 50.0
        components.append(_bounded_score(score))
    return sum(components) / len(components)


def _mean_reversion_strategy(enriched: dict[str, pd.DataFrame], analyses: dict[str, TimeframeAnalysis]) -> float:
    scores: list[float] = []
    for key in ("1m", "5m"):
        close = enriched[key]["close"].tail(20)
        deviation = float(close.std(ddof=0))
        z_score = (float(close.iloc[-1]) - float(close.mean())) / deviation if deviation > 0 else 0.0
        rsi_distance = analyses[key].rsi - 50
        scores.append(_bounded_score(50 - z_score * 18 - rsi_distance * 0.35))
    return sum(scores) / len(scores)


def _market_structure_strategy(enriched: dict[str, pd.DataFrame]) -> float:
    """Objektive BOS-/Pullback-Naeherung aus den Marktstruktur-Videos."""

    scores: list[float] = []
    for key in ("5m", "15m"):
        frame = enriched[key]
        smart_money = _smart_money_context(frame)
        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        close = float(latest["close"])
        swing_high = float(latest["swing_high_12"])
        swing_low = float(latest["swing_low_12"])
        fast = float(latest["ema_fast"])
        slow = float(latest["ema_slow"])
        if smart_money.bullish_reversal:
            score = 94.0
        elif smart_money.bearish_reversal:
            score = 6.0
        elif smart_money.demand_retest:
            score = 82.0
        elif close > swing_high:
            score = 86.0
        elif close < swing_low:
            score = 14.0
        elif close > fast > slow and float(latest["low"]) <= fast * 1.006 and close > float(previous["close"]):
            score = 74.0
        elif swing_high > swing_low:
            score = 20 + 60 * ((close - swing_low) / (swing_high - swing_low))
        else:
            score = 50.0
        scores.append(_bounded_score(score))
    return sum(scores) / len(scores)


def _ott_ut_strategy(enriched: dict[str, pd.DataFrame]) -> float:
    """Kombiniert OTT, UT-ATR-Stop und Linear-Regression-Kerzen als Trendbestaetigung."""

    timeframe_scores: list[float] = []
    for key in ("5m", "15m"):
        latest = enriched[key].iloc[-1]
        close = float(latest["close"])
        checks = (
            close > float(latest["ut_stop"]),
            float(latest["ott_support"]) > float(latest["ott"]),
            float(latest["linreg_close"]) > float(latest["linreg_open"]),
            float(latest["linreg_slope"]) > 0,
        )
        timeframe_scores.append(sum(checks) / len(checks) * 100)
    return timeframe_scores[0] * 0.65 + timeframe_scores[1] * 0.35


def _price_impulse(frame: pd.DataFrame, bars: int) -> float:
    """Misst jüngste Richtung und Persistenz relativ zur aktuellen Volatilität."""

    if len(frame) <= bars:
        return 0.0
    close = frame["close"].astype(float)
    latest_atr = _latest_finite(frame, "atr_14", float(close.iloc[-1]) * 0.002)
    scale = max(latest_atr * np.sqrt(bars), float(close.iloc[-1]) * 0.0005)
    move = float(close.iloc[-1] - close.iloc[-1 - bars]) / scale
    persistence = float(np.sign(close.diff().tail(bars).fillna(0.0)).mean())
    return float(np.clip(move * 0.72 + persistence * 0.28, -2.0, 2.0))


def _horizon_price_action(enriched: dict[str, pd.DataFrame], minutes: int) -> float:
    """Reagiert schneller auf Wendepunkte als die nachlaufenden EMA-/OTT-Komponenten."""

    configurations = {
        5: (("1m", 3, 0.50), ("1m", 8, 0.30), ("5m", 1, 0.20)),
        15: (("1m", 8, 0.25), ("5m", 2, 0.50), ("15m", 1, 0.25)),
        30: (("5m", 3, 0.35), ("5m", 6, 0.25), ("15m", 2, 0.30), ("1h", 1, 0.10)),
        60: (("5m", 6, 0.20), ("15m", 3, 0.45), ("1h", 1, 0.35)),
        120: (("15m", 4, 0.35), ("1h", 2, 0.50), ("1d", 1, 0.15)),
    }
    impulse = sum(
        _price_impulse(enriched[key], bars) * weight
        for key, bars, weight in configurations[minutes]
    )
    return _bounded_score(50 + impulse * 22)


def _trend_horizons(
    analyses: dict[str, TimeframeAnalysis],
    enriched: dict[str, pd.DataFrame],
    price: float,
    ensemble_score: float,
    minimum_move_percent: float = 0.15,
) -> tuple[TrendForecast, ...]:
    """Leitet getrennte Horizonte aus Preisaktion, Zeitebenen und ATR ab."""

    weight_sets = {
        5: {"1m": 0.50, "5m": 0.35, "15m": 0.05},
        15: {"1m": 0.20, "5m": 0.45, "15m": 0.25},
        30: {"1m": 0.10, "5m": 0.30, "15m": 0.40, "1h": 0.10},
        60: {"5m": 0.15, "15m": 0.35, "1h": 0.30, "1d": 0.10},
        120: {"5m": 0.10, "15m": 0.25, "1h": 0.35, "1d": 0.15},
    }
    one_atr = _latest_finite(enriched["1m"], "atr_14", price * 0.003)
    five_atr = _latest_finite(enriched["5m"], "atr_14", price * 0.006)
    hour_atr = _latest_finite(enriched["1h"], "atr_14", price * 0.018)
    price_action_weights = {5: 0.70, 15: 0.60, 30: 0.40, 60: 0.30, 120: 0.20}
    forecasts: list[TrendForecast] = []
    for minutes, weights in weight_sets.items():
        timeframe_weight = sum(weights.values())
        lagging_score = sum(analyses[key].score * weight for key, weight in weights.items())
        lagging_score += ensemble_score * (1 - timeframe_weight)
        price_action_score = _horizon_price_action(enriched, minutes)
        price_action_weight = price_action_weights[minutes]
        horizon_score = (
            price_action_score * price_action_weight
            + lagging_score * (1 - price_action_weight)
        )
        volatility_inputs = [
            one_atr * np.sqrt(minutes),
            five_atr * np.sqrt(minutes / 5),
            price * 0.0015,
        ]
        if minutes >= 60:
            volatility_inputs.append(hour_atr * np.sqrt(minutes / 60))
        volatility = max(volatility_inputs)
        directional_shift = ((horizon_score - 50) / 50) * volatility * 0.75
        expected = max(price + directional_shift, 0.001)
        expected_return_percent = directional_shift / price * 100
        direction = (
            "STEIGEND"
            if expected_return_percent > minimum_move_percent
            else "FALLEND"
            if expected_return_percent < -minimum_move_percent
            else "SEITWÄRTS"
        )
        disagreement = abs(price_action_score - lagging_score)
        confidence = np.clip(
            45.0 + abs(horizon_score - 50) * 1.25 - disagreement * 0.30,
            35.0,
            82.0,
        )
        forecasts.append(
            TrendForecast(
                minutes=minutes,
                direction=direction,
                expected_price=round(expected, 3),
                expected_low=round(max(expected - volatility, 0.001), 3),
                expected_high=round(expected + volatility, 3),
                confidence=round(confidence, 1),
            )
        )
    return tuple(forecasts)


def build_strategy_ensemble(
    analyses: dict[str, TimeframeAnalysis],
    enriched: dict[str, pd.DataFrame],
    price: float,
    *,
    spread_percent: float | None = None,
    order_imbalance: float | None = None,
    external_context: ExternalMarketContext | None = None,
) -> StrategyEnsemble:
    """Kombiniert Trend, Momentum, Ausbruch, Rücklauf und höheren Kontext ohne Look-ahead."""

    trend_score = sum(
        analyses[key].score * weight
        for key, weight in {"1m": 0.30, "5m": 0.35, "15m": 0.25, "1h": 0.10}.items()
    )
    momentum_score = _momentum_strategy(enriched, analyses)
    breakout_score = _breakout_strategy(enriched, analyses)
    reversion_score = _mean_reversion_strategy(enriched, analyses)
    context_score = sum(
        analyses[key].score * weight
        for key, weight in {"1h": 0.50, "1d": 0.30, "1wk": 0.15, "1mo": 0.05}.items()
    )
    structure_score = _market_structure_strategy(enriched)
    ott_ut_score = _ott_ut_strategy(enriched)

    five_minute = enriched["5m"]
    latest_five = five_minute.iloc[-1]
    atr_five = _latest_finite(five_minute, "atr_14", price * 0.006)
    ema_separation = abs(float(latest_five["ema_fast"]) - float(latest_five["ema_slow"])) / max(
        atr_five, price * 0.001
    )
    aligned_trend = (analyses["1m"].score >= 58 and analyses["5m"].score >= 58) or (
        analyses["1m"].score <= 42 and analyses["5m"].score <= 42
    )
    recent = five_minute.tail(12)
    recent_range = (float(recent["high"].max()) - float(recent["low"].min())) / price
    if aligned_trend and ema_separation >= 0.10:
        regime = "Trend"
        weights = {
            "Trend": 0.22,
            "Momentum": 0.18,
            "Ausbruch": 0.12,
            "Rücklauf": 0.02,
            "Kontext": 0.08,
            "Marktstruktur": 0.18,
            "OTT/UT": 0.20,
        }
    elif recent_range >= 0.04:
        regime = "hohe Volatilität"
        weights = {
            "Trend": 0.18,
            "Momentum": 0.14,
            "Ausbruch": 0.14,
            "Rücklauf": 0.12,
            "Kontext": 0.12,
            "Marktstruktur": 0.14,
            "OTT/UT": 0.16,
        }
    else:
        regime = "Seitwärts"
        weights = {
            "Trend": 0.10,
            "Momentum": 0.10,
            "Ausbruch": 0.08,
            "Rücklauf": 0.30,
            "Kontext": 0.12,
            "Marktstruktur": 0.14,
            "OTT/UT": 0.16,
        }

    strategy_scores = {
        "Trend": trend_score,
        "Momentum": momentum_score,
        "Ausbruch": breakout_score,
        "Rücklauf": reversion_score,
        "Kontext": context_score,
        "Marktstruktur": structure_score,
        "OTT/UT": ott_ut_score,
    }
    score = sum(strategy_scores[name] * weight for name, weight in weights.items())
    if order_imbalance is not None and np.isfinite(order_imbalance):
        score += min(max(order_imbalance, -1.0), 1.0) * 4
    if spread_percent is not None and spread_percent > 0.6:
        score = 50 + (score - 50) * 0.70
    if external_context is not None and external_context.available:
        context_adjustment = np.clip((external_context.score - 50) * 0.18, -7.0, 7.0)
        score += float(context_adjustment)
    score = round(_bounded_score(score), 1)

    one_minute_atr = _latest_finite(enriched["1m"], "atr_14", price * 0.006)
    expected_move = max(atr_five * 1.35, one_minute_atr * np.sqrt(15), price * 0.003)
    directional_shift = ((score - 50) / 50) * expected_move * 0.35
    expected_low = max(price + directional_shift - expected_move, 0.001)
    expected_high = price + directional_shift + expected_move
    votes = tuple(
        f"{name} {value:.0f} {'↑' if value >= 58 else '↓' if value <= 42 else '→'}"
        for name, value in strategy_scores.items()
    )
    horizons = _trend_horizons(
        analyses,
        enriched,
        price,
        score,
        minimum_move_percent=0.15,
    )
    short_direction_score = sum(
        {"STEIGEND": 1.0, "FALLEND": -1.0, "SEITWÄRTS": 0.0}[forecast.direction] * weight
        for forecast, weight in zip(horizons[:3], (0.50, 0.30, 0.20), strict=True)
    )
    direction = (
        "EHER STEIGEND"
        if short_direction_score >= 0.45
        else "EHER FALLEND"
        if short_direction_score <= -0.45
        else "SEITWÄRTS"
    )
    return StrategyEnsemble(
        score=score,
        direction=direction,
        expected_low=float(round(expected_low, 3)),
        expected_high=float(round(expected_high, 3)),
        regime=regime,
        votes=votes,
        positive_votes=sum(value >= 58 for value in strategy_scores.values()),
        negative_votes=sum(value <= 42 for value in strategy_scores.values()),
        horizons=horizons,
    )


def build_intraday_signal(
    analyses: dict[str, TimeframeAnalysis],
    enriched: dict[str, pd.DataFrame],
    position: FocusPosition,
    *,
    now: datetime | None = None,
    enforce_market_hours: bool = True,
    maximum_data_age_minutes: float = 4.0,
    live_price: float | None = None,
    session_close: time = time(23, 0),
    spread_percent: float | None = None,
    order_imbalance: float | None = None,
    require_volume_confirmation: bool = True,
    enforce_liquidity_filter: bool = True,
    external_context: ExternalMarketContext | None = None,
) -> IntradaySignal:
    current_time = now or datetime.now(UTC)
    required = ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo")
    missing = [key for key in required if key not in analyses]
    fallback_price = next((value.price for value in analyses.values()), 0.0)
    if missing:
        return IntradaySignal(
            action="NO_SIGNAL",
            headline="KEIN SIGNAL – Daten unvollständig",
            score=50.0,
            strength="keine",
            color="#64748b",
            current_price=fallback_price,
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            target=None,
            holding_period=ADAPTIVE_HOLDING_PERIOD,
            reasons=("Für einen Kurzfrist-Trade müssen alle sieben Zeitebenen verfügbar sein.",),
            warning="Fehlend: " + ", ".join(SPEC_BY_KEY[key].label for key in missing),
            data_age_minutes=float("inf"),
            market_open=False,
        )

    minute = analyses["1m"]
    candle_end = minute.data_timestamp.astimezone(UTC) + timedelta(minutes=1)
    age_minutes = max((current_time.astimezone(UTC) - candle_end).total_seconds() / 60, 0.0)
    market_open = _is_german_market_open(current_time, session_close)
    price = live_price if live_price is not None and live_price > 0 else minute.price
    minute_data = enriched["1m"]
    latest = minute_data.iloc[-1]
    one_minute_atr = float(latest["atr_14"])
    if not np.isfinite(one_minute_atr) or one_minute_atr <= 0:
        one_minute_atr = price * 0.006
    entry_low = price - (0.10 * one_minute_atr)
    entry_high = price + (0.15 * one_minute_atr)

    forecast = build_strategy_ensemble(
        analyses,
        enriched,
        price,
        spread_percent=spread_percent,
        order_imbalance=order_imbalance,
        external_context=external_context,
    )
    score = forecast.score
    five_minute_atr = _latest_finite(enriched["5m"], "atr_14", price * 0.006)
    risk_distance = max(one_minute_atr, five_minute_atr * 0.75)
    stop_loss = price - risk_distance
    target = min(price + 2.25 * risk_distance, forecast.expected_high)

    if enforce_market_hours and not market_open:
        return IntradaySignal(
            "NO_SIGNAL",
            "KEIN SIGNAL – deutscher Markt geschlossen",
            score,
            _signal_strength(score),
            "#64748b",
            price,
            None,
            None,
            None,
            None,
            ADAPTIVE_HOLDING_PERIOD,
            ("Kurzfristige Signale werden nur während der Handelszeit der Kursquelle freigegeben.",),
            "Der nächste Kurs kann mit einer Lücke eröffnen; jetzt keine Handlung ableiten.",
            age_minutes,
            False,
            forecast.direction,
            forecast.expected_low,
            forecast.expected_high,
            forecast.regime,
            forecast.votes,
            spread_percent,
            forecast.horizons,
        )
    if age_minutes > maximum_data_age_minutes:
        return IntradaySignal(
            "NO_SIGNAL",
            "KEIN SIGNAL – Kurs ist zu stark verzögert",
            score,
            _signal_strength(score),
            "#64748b",
            price,
            None,
            None,
            None,
            None,
            ADAPTIVE_HOLDING_PERIOD,
            (f"Die letzte abgeschlossene 1-Minuten-Kerze ist {age_minutes:.1f} Minuten alt.",),
            "Für einen kurzfristigen Trade bis 120 Minuten sind verzögerte Gratisdaten nicht sicher genug.",
            age_minutes,
            market_open,
            forecast.direction,
            forecast.expected_low,
            forecast.expected_high,
            forecast.regime,
            forecast.votes,
            spread_percent,
            forecast.horizons,
        )

    observed_short_volume = max(
        value
        for value in (
            analyses["1m"].relative_volume or 0.0,
            analyses["5m"].relative_volume or 0.0,
        )
    ) >= 0.8
    short_volume = observed_short_volume or not require_volume_confirmation
    wide_spread = spread_percent is not None and spread_percent > 0.6
    liquidity_veto = wide_spread and enforce_liquidity_filter
    external_risk_veto = bool(
        external_context is not None
        and external_context.available
        and external_context.score <= 25
    )
    latest_five = enriched["5m"].iloc[-1]
    latest_fifteen = enriched["15m"].iloc[-1]
    five_atr = _latest_finite(enriched["5m"], "atr_14", price * 0.006)
    trend_confirmation_votes = (
        float(latest_five["close"]) > float(latest_five["ut_stop"]),
        float(latest_five["ott_support"]) > float(latest_five["ott"]),
        float(latest_five["linreg_close"]) > float(latest_five["linreg_open"]),
        float(latest_five["linreg_slope"]) > 0,
        float(latest_fifteen["close"]) > float(latest_fifteen["ut_stop"]),
    )
    confirmed_trend = sum(trend_confirmation_votes) >= 4
    not_chasing = (
        float(latest_five["close"]) - float(latest_five["ema_fast"])
        <= max(five_atr * 1.2, price * 0.002)
    )
    smart_money = _smart_money_context(enriched["5m"])
    opening_reversal = _us_opening_reversal(enriched["1m"], current_time, spread_percent)
    microtrend = _microtrend_continuation(enriched["1m"], spread_percent)
    profit_exhaustion = _profit_exhaustion(enriched["1m"])
    opening_context_ok = analyses["1h"].score >= 25 and analyses["1d"].score >= 25
    opening_trigger = (
        opening_reversal.active
        and opening_context_ok
        and not liquidity_veto
        and not external_risk_veto
    )
    microtrend_context_ok = (
        analyses["5m"].score >= 50
        and analyses["15m"].score >= 50
        and analyses["1h"].score >= 45
        and analyses["1d"].score >= 40
        and forecast.score >= 58
        and forecast.horizons[0].direction == "STEIGEND"
        and forecast.horizons[1].direction != "FALLEND"
    )
    microtrend_trigger = (
        microtrend.active
        and microtrend_context_ok
        and not liquidity_veto
        and not external_risk_veto
    )
    if opening_trigger and opening_reversal.stop_loss is not None and opening_reversal.target is not None:
        stop_loss = opening_reversal.stop_loss
        target = opening_reversal.target
        entry_low = price - 0.05 * one_minute_atr
        entry_high = price + 0.10 * one_minute_atr
    elif microtrend_trigger and microtrend.stop_loss is not None and microtrend.target is not None:
        stop_loss = microtrend.stop_loss
        target = microtrend.target
        entry_low = price - 0.05 * one_minute_atr
        entry_high = price + 0.10 * one_minute_atr
    setup_confirmation = (
        analyses["1m"].setup in {"Ausbruch", "Trend-Rücksetzer"}
        or smart_money.bullish_reversal
        or smart_money.demand_retest
    )
    short_trigger = (
        analyses["1m"].score >= 62
        and analyses["5m"].score >= 62
        and analyses["15m"].score >= 52
        and analyses["1m"].rsi <= 73
        and setup_confirmation
        and short_volume
        and forecast.positive_votes >= 5
        and forecast.horizons[0].direction == "STEIGEND"
        and forecast.horizons[1].direction != "FALLEND"
        and confirmed_trend
        and not_chasing
        and not smart_money.bearish_reversal
        and not liquidity_veto
        and not external_risk_veto
    )
    context_veto = analyses["1h"].score < 38 or analyses["1d"].score < 35
    bearish_exit = analyses["1m"].score <= 38 and analyses["5m"].score <= 42
    reasons = (
        (
            "Markt/Nachrichten: " + " · ".join(external_context.reasons)
            if external_context is not None and external_context.available
            else "Markt/Nachrichten: Zusatzkontext nicht verfügbar · technisch neutral behandelt"
        ),
        (
            "US-Eröffnung bestätigt: starker Abverkauf · vorheriges Tief geholt · "
            "bullisch zurückerobert"
            if opening_reversal.active
            else "US-Eröffnung: kein bestätigter Sell-Side-Sweep mit Rückeroberung"
        ),
        (
            "Mikrotrend bestätigt: vier grüne Kerzen · steigende Tiefs · lokales Hoch gebrochen"
            if microtrend.active
            else "Mikrotrend: keine bestätigte Kerzentreppe mit Ausbruch"
        ),
        f"Marktphase {forecast.regime}: " + " · ".join(forecast.votes),
        f"1 Minute {analyses['1m'].score:.0f} · 5 Minuten {analyses['5m'].score:.0f} · "
        f"15 Minuten {analyses['15m'].score:.0f}",
        (
            f"Volumen {'bestätigt' if observed_short_volume else 'zu schwach'} · "
            if require_volume_confirmation
            else "L&S-Bid-Quelle ohne Volumen · Preisbestätigung aktiv · "
        )
        + (f"Spread {spread_percent:.2f} %" if spread_percent is not None else "Spread nicht verfügbar"),
        (
            "Marktstruktur + OTT/UT + LinReg bestätigt"
            if confirmed_trend
            else "OTT/UT/LinReg noch nicht gemeinsam bestätigt"
        )
        + (" · Einstieg nicht überdehnt" if not_chasing else " · Kurs bereits zu weit vom EMA entfernt"),
        "Liquidität/Orderblock: " + smart_money.event,
    )

    action = "WAIT"
    headline = "WARTEN – noch kein sauberer Einstieg"
    color = "#f59e0b"
    warning = "Kein Trade, bis 1- und 5-Minuten-Chart gemeinsam bestätigen."
    if liquidity_veto:
        warning = "Kein Einstieg: Der Geld-/Brief-Spread ist für diesen kurzfristigen Trade zu groß."
    if external_risk_veto:
        warning = "Kein Einstieg: Nachrichten- und Marktumfeld zeigen derzeit außergewöhnlich hohes Risiko."
    if position.invested:
        if profit_exhaustion:
            action, headline, color = "SELL", "VERKAUFEN – Aufwärtsschwung lässt nach", "#ef4444"
            warning = "Nach extremem 1-Minuten-RSI bestätigt eine rote Kerze die Gewinnmitnahme."
        elif opening_trigger:
            if position.average_price is not None and price >= position.average_price:
                action, headline, color = "ADD", "NACHKAUFEN – US-Eröffnungs-Reversal bestätigt", "#22c55e"
                warning = "Der Abverkauf wurde zurückerobert; Stop und Kostenhürde bleiben verbindlich."
            else:
                action, headline, color = "HOLD", "HALTEN – US-Eröffnungs-Reversal bestätigt", "#38bdf8"
                warning = "Das Reversal spricht gegen einen Verkauf am Tief, aber nicht für Verbilligen."
        elif bearish_exit or score <= 38:
            action, headline, color = "SELL", "VERKAUFEN – kurzfristiger Trend kippt", "#ef4444"
            warning = "Signal bezieht sich auf den kurzfristigen Trade; Ausführung und Spread selbst prüfen."
        elif short_trigger and not context_veto and score >= 64:
            if position.average_price is not None and price >= position.average_price:
                action, headline, color = "ADD", "NACHKAUFEN – erneute Intraday-Bestätigung", "#22c55e"
                warning = "Nicht verbilligen: Das Nachkaufsignal gilt nur oberhalb deines Einstandskurses."
            else:
                action, headline, color = "HOLD", "HALTEN – kein Nachkauf im Verlust", "#38bdf8"
                warning = "Ein positives Setup reicht nicht zum Verbilligen einer verlustreichen Position."
        else:
            action, headline, color = "HOLD", "HALTEN / BEOBACHTEN", "#38bdf8"
            warning = "Stop beachten; ohne neue 1- und 5-Minuten-Bestätigung nicht aufstocken."
    elif opening_trigger:
        action, headline, color = "BUY", "KAUFEN – bestätigtes US-Eröffnungs-Reversal", "#22c55e"
        warning = "Nur nach Rückeroberung; der Stop liegt knapp unter dem zurückgewonnenen Tief."
    elif microtrend_trigger:
        action, headline, color = "BUY", "KAUFEN – bullischer Mikrotrend bestätigt", "#22c55e"
        warning = "Frühes Fortsetzungssetup; steigende Kerzen allein reichen ohne Ausbruch nicht aus."
    elif short_trigger and not context_veto and score >= 64:
        action, headline, color = "BUY", "KAUFEN – kurzfristiges technisches Signal", "#22c55e"
        warning = "Adaptiv halten; bei Stop oder bestätigtem Trendbruch ist das Setup ungültig."
        if wide_spread:
            warning = "Technisches Kaufsignal vorhanden; der aktuelle Spread ist für eine Ausführung zu teuer."

    return IntradaySignal(
        action=action,
        headline=headline,
        score=score,
        strength=_signal_strength(score),
        color=color,
        current_price=price,
        entry_low=entry_low if action in {"BUY", "ADD"} else None,
        entry_high=entry_high if action in {"BUY", "ADD"} else None,
        stop_loss=stop_loss if action in {"BUY", "ADD", "HOLD"} else None,
        target=target if action in {"BUY", "ADD", "HOLD"} else None,
        holding_period=ADAPTIVE_HOLDING_PERIOD,
        reasons=reasons,
        warning=warning,
        data_age_minutes=age_minutes,
        market_open=market_open,
        forecast_direction=forecast.direction,
        forecast_low=forecast.expected_low,
        forecast_high=forecast.expected_high,
        market_regime=forecast.regime,
        strategy_votes=forecast.votes,
        spread_percent=spread_percent,
        trend_forecasts=forecast.horizons,
        demand_low=smart_money.demand_low,
        demand_high=smart_money.demand_high,
        liquidity_low=smart_money.liquidity_low,
        liquidity_high=smart_money.liquidity_high,
        structure_event=(
            PROFIT_EXHAUSTION_EVENT
            if action == "SELL" and profit_exhaustion
            else opening_reversal.event
            if opening_reversal.active
            else microtrend.event
            if microtrend.active
            else smart_money.event
        ),
        external_context_score=external_context.score if external_context is not None else 50.0,
        external_context_reasons=external_context.reasons if external_context is not None else (),
        latest_news=external_context.headlines if external_context is not None else (),
    )


def build_market_signal(
    analyses: dict[str, TimeframeAnalysis],
    enriched: dict[str, pd.DataFrame],
    **signal_options: object,
) -> IntradaySignal:
    """Liefert KAUFEN/VERKAUFEN unabhängig von einer privaten Depotposition."""

    entry_signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(),
        **signal_options,
    )
    if entry_signal.action == "BUY" and entry_signal.structure_event in {
        US_OPENING_REVERSAL_EVENT,
        MICROTREND_CONTINUATION_EVENT,
    }:
        return entry_signal
    exit_signal = build_intraday_signal(
        analyses,
        enriched,
        FocusPosition(invested=True, average_price=entry_signal.current_price, quantity=1.0),
        **signal_options,
    )
    return exit_signal if exit_signal.action == "SELL" else entry_signal
