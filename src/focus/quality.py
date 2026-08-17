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
) -> dict[int, dict[str, float | int | bool | None]]:
    """Liefert die Freigabe je Horizont aus Live- und Replay-Ergebnissen."""

    versions = (model_version, f"{model_version}-replay")
    return {
        minutes: store.focus_forecast_quality(
            symbol=DWAVE_INSTRUMENT.exchange_symbol,
            horizon_minutes=minutes,
            model_version=versions,
            target_accuracy=TARGET_ACCURACY,
        )
        for minutes in FORECAST_HORIZONS
    }


def released_horizon_payloads(
    signal: IntradaySignal,
    quality: dict[int, dict[str, float | int | bool | None]],
) -> tuple[dict[str, object], ...]:
    """Friert die damalige Freigabe mit der Prognose ein; spaetere Daten aendern sie nicht."""

    payloads: list[dict[str, object]] = []
    for item in signal.trend_forecasts:
        validation = quality.get(item.minutes, {})
        threshold = validation.get("threshold")
        qualified = bool(validation.get("qualified"))
        released = bool(
            qualified
            and threshold is not None
            and item.confidence >= float(threshold)
        )
        verification_accuracy = validation.get("verification_accuracy")
        verification_samples = int(validation.get("verification_samples") or 0)
        total = int(validation.get("total") or 0)
        raw_accuracy = validation.get("raw_accuracy")
        if released:
            reason = (
                f"75%-Freigabe: {float(verification_accuracy):.1f} % in "
                f"{verification_samples} späteren Fällen"
            )
        elif qualified:
            reason = (
                f"Nur Prüfung: Modellstärke {item.confidence:.0f} % unter "
                f"Freigabeschwelle {float(threshold):.0f} %"
            )
        elif total < 60:
            reason = f"Nur Prüfung: erst {total} von mindestens 60 abgeschlossenen Fällen"
        elif raw_accuracy is None:
            reason = "Nur Prüfung: Zielquote 75 % noch nicht bestätigt"
        else:
            reason = (
                f"Nur Prüfung: Zielquote 75 % nicht bestätigt "
                f"(alle Fälle {float(raw_accuracy):.1f} %)"
            )
        payloads.append(
            {
                "minutes": item.minutes,
                "direction": item.direction,
                "expected_price": item.expected_price,
                "expected_low": item.expected_low,
                "expected_high": item.expected_high,
                "confidence": item.confidence,
                "released": released,
                "release_reason": reason,
                "quality_accuracy": verification_accuracy,
                "quality_samples": verification_samples,
                "quality_coverage": validation.get("coverage"),
            }
        )
    return tuple(payloads)
