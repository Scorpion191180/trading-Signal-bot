"""yfinance-Implementierung hinter der austauschbaren Datenanbieter-Schnittstelle."""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from .base import MarketDataRequest, ProviderError, completed_candles, normalize_ohlcv, validate_history


class YFinanceMarketDataProvider:
    name = "yfinance"
    is_demo = False
    supported_intervals = {"1m", "5m", "15m", "30m", "60m", "1h", "1d"}

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        if request.interval not in self.supported_intervals:
            raise ProviderError(f"Intervall {request.interval!r} wird nicht unterstützt.")
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - Installationsfehler
            raise ProviderError("yfinance ist nicht installiert.") from exc
        try:
            cache_path = Path("data/yfinance_cache")
            cache_path.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(cache_path))
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="The 'generic' unit for NumPy timedelta is deprecated.*",
                    category=DeprecationWarning,
                )
                frame = yf.download(
                    request.symbol.upper().strip(),
                    period=request.period,
                    interval=request.interval,
                    prepost=request.prepost,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                    timeout=15,
                )
            normalized = normalize_ohlcv(frame, request.symbol.upper().strip())
            result = validate_history(completed_candles(normalized, request.interval))
            result.attrs["provider"] = self.name
            return result
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Kursdaten konnten nicht geladen werden: {exc}") from exc
