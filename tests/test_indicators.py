from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.analysis.indicators import add_indicators, atr, rsi
from src.data.base import completed_candles, normalize_ohlcv


def test_required_indicators_are_calculated(market_frame):
    result = add_indicators(market_frame)
    required = {
        "ema_20",
        "ema_50",
        "ema_200",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "vwap",
        "atr_14",
        "bb_upper",
        "bb_lower",
        "relative_volume",
    }
    assert required.issubset(result.columns)
    assert result["bb_upper"].iloc[-1] > result["bb_lower"].iloc[-1]
    assert result["ema_20"].iloc[-1] > result["ema_200"].iloc[-1]


def test_rsi_and_atr_are_bounded_and_reproducible(market_frame):
    first = rsi(market_frame["close"])
    second = rsi(market_frame["close"])
    assert np.allclose(first.dropna(), second.dropna())
    assert first.dropna().between(0, 100).all()
    assert (atr(market_frame).dropna() > 0).all()


def test_vwap_uses_volume(market_frame):
    result = add_indicators(market_frame)
    assert result["vwap"].notna().all()
    assert result["vwap"].iloc[-1] <= market_frame["high"].max()


def test_yfinance_close_and_adjusted_close_do_not_create_duplicates(market_frame):
    yfinance_like = market_frame.rename(columns={column: column.title() for column in market_frame.columns})
    yfinance_like["Adj Close"] = yfinance_like["Close"] * 0.99
    yfinance_like.columns = pd.MultiIndex.from_product([yfinance_like.columns, ["AAPL"]])
    result = normalize_ohlcv(yfinance_like, "AAPL")
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]
    assert result.columns.is_unique


def test_incomplete_candle_is_excluded(market_frame):
    current_start = pd.Timestamp("2026-08-04 12:00", tz="UTC")
    data = market_frame.tail(2).copy()
    data.index = [current_start - timedelta(minutes=5), current_start]
    result = completed_candles(data, "5m", now=current_start + timedelta(minutes=2))
    assert list(result.index) == [current_start - timedelta(minutes=5)]
