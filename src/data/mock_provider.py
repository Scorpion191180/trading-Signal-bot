"""Deterministische Demo-Kursdaten für Offline-Betrieb und Tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import numpy as np
import pandas as pd

from .base import MarketDataRequest, normalize_ohlcv


class MockMarketDataProvider:
    name = "Demo-Daten (deterministisch)"
    is_demo = True

    def __init__(self, rows: int = 420) -> None:
        self.rows = rows

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "1d": 1440}.get(
            request.interval, 5
        )
        seed = int(hashlib.sha256(request.symbol.upper().encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        end = pd.Timestamp.now(tz="UTC").floor(f"{minutes}min") - timedelta(minutes=minutes)
        index = pd.date_range(end=end, periods=self.rows, freq=f"{minutes}min", tz="UTC")
        drift = 0.00035 if seed % 2 else -0.00005
        returns = rng.normal(drift, 0.004, self.rows)
        close = 40.0 * np.exp(np.cumsum(returns))
        open_ = np.r_[close[0], close[:-1]]
        spread = np.abs(rng.normal(0.003, 0.001, self.rows))
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        volume = rng.integers(40_000, 300_000, self.rows).astype(float)
        volume[-1] *= 1.8
        return normalize_ohlcv(
            pd.DataFrame(
                {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                index=index,
            )
        )
