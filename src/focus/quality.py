"""Zeitlich saubere Freigabe von Richtungsprognosen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .analysis import DWAVE_INSTRUMENT, IntradaySignal

if TYPE_CHECKING:
    from src.database import DataStore


FORECAST_HORIZONS = (5, 15, 30, 60, 120)
TARGET_ACCURACY = 75.0


def forecast_quality_map(
    store: DataStore,
    model_version: str,
    *,
    symbol: str = DWAVE_INSTRUMENT.exchange_symbol,
) -> dict[int, dict[str, float | int | bool | None]]:
    """Liefert die zeitlich gemessene Trefferqualität je Horizont."""

    versions = (model_version, f"{model_version}-replay")
    return {
        minutes: store.focus_forecast_quality(
            symbol=symbol,
            horizon_minutes=minutes,
            model_version=versions,
            target_accuracy=TARGET_ACCURACY,
        )
        for minutes in FORECAST_HORIZONS
    }


def forecast_horizon_payloads(
    signal: IntradaySignal,
    quality: dict[int, dict[str, float | int | bool | None]],
) -> tuple[dict[str, object], ...]:
    """Speichert jede Prognose; 75 % ist ein Messziel und keine Anzeigeschwelle."""

    payloads: list[dict[str, object]] = []
    for item in signal.trend_forecasts:
        validation = quality.get(item.minutes, {})
        verification_accuracy = validation.get("verification_accuracy")
        verification_samples = int(validation.get("verification_samples") or 0)
        total = int(validation.get("total") or 0)
        raw_accuracy = validation.get("raw_accuracy")
        if verification_accuracy is not None:
            reason = (
                f"Immer sichtbare Prognose · bisher {float(verification_accuracy):.1f} % "
                f"in {verification_samples} zeitlich späteren Testfällen"
            )
        elif total < 60:
            reason = f"Immer sichtbare Prognose · bisher {total} abgeschlossene Fälle"
        elif raw_accuracy is None:
            reason = "Immer sichtbare Prognose · Trefferquote noch nicht messbar"
        else:
            reason = (
                f"Immer sichtbare Prognose · bisher {float(raw_accuracy):.1f} % "
                "Trefferquote"
            )
        payloads.append(
            {
                "minutes": item.minutes,
                "direction": item.direction,
                "expected_price": item.expected_price,
                "expected_low": item.expected_low,
                "expected_high": item.expected_high,
                "confidence": item.confidence,
                "released": True,
                "release_reason": reason,
                "quality_accuracy": verification_accuracy,
                "quality_samples": verification_samples,
                "quality_coverage": validation.get("coverage"),
            }
        )
    return tuple(payloads)
