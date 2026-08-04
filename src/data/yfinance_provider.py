"""yfinance-Implementierung hinter der austauschbaren Datenanbieter-Schnittstelle."""

from __future__ import annotations

import pandas as pd

from .base import MarketDataRequest, ProviderError, completed_candles, normalize_ohlcv


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
            frame = yf.download(
                request.symbol.upper().strip(),
                period=request.period,
                interval=request.interval,
                prepost=request.prepost,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            normalized = normalize_ohlcv(frame, request.symbol.upper().strip())
            return completed_candles(normalized, request.interval)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Kursdaten konnten nicht geladen werden: {exc}") from exc
