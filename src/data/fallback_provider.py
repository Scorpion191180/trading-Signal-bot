"""Qualitätsgeprüfte Kette mehrerer realer Kursdatenanbieter."""

from __future__ import annotations

import pandas as pd

from .base import MarketDataProvider, MarketDataRequest, ProviderError


class FallbackMarketDataProvider:
    is_demo = False

    def __init__(self, providers: list[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("Mindestens eine reale Kursdatenquelle ist erforderlich.")
        if any(provider.is_demo for provider in providers):
            raise ValueError("Demo-Anbieter dürfen nicht in die Realdaten-Fallbackkette gelangen.")
        self.providers = tuple(providers)

    @property
    def name(self) -> str:
        return " → ".join(provider.name for provider in self.providers)

    def history(self, request: MarketDataRequest) -> pd.DataFrame:
        errors: list[str] = []
        for provider in self.providers:
            try:
                frame = provider.history(request)
                frame.attrs["provider"] = str(frame.attrs.get("provider", provider.name))
                if errors:
                    frame.attrs["fallback_reason"] = " | ".join(errors)
                return frame
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
        raise ProviderError("Alle realen Kursdatenquellen sind ausgefallen oder unvollständig: " + " | ".join(errors))
