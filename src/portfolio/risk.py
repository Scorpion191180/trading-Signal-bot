"""Nicht durch Lernen überschreibbare Risikoschutzregeln."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import StrategyProfile


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    quantity: float
    position_value: float
    risk_amount: float
    reason: str


def calculate_position_size(
    *,
    portfolio_value: float,
    available_cash: float,
    entry_price: float,
    stop_loss: float,
    profile: StrategyProfile,
    open_positions: int,
    relative_volume: float,
    data_is_fresh: bool,
    spread_pct: float,
) -> RiskDecision:
    """Begrenzt eine Position gleichzeitig nach Kapitalanteil und Stop-Risiko."""

    if not data_is_fresh:
        return RiskDecision(False, 0, 0, 0, "Kursdaten sind veraltet.")
    if entry_price <= 0 or stop_loss <= 0 or stop_loss >= entry_price:
        return RiskDecision(False, 0, 0, 0, "Stop-Loss muss sinnvoll unter dem Einstieg liegen.")
    if open_positions >= profile.max_open_positions:
        return RiskDecision(False, 0, 0, 0, "Maximale Zahl offener Positionen erreicht.")
    if relative_volume < profile.min_relative_volume:
        return RiskDecision(False, 0, 0, 0, "Relatives Volumen ist für diese Strategie zu gering.")
    if spread_pct > profile.max_spread_pct:
        return RiskDecision(False, 0, 0, 0, "Geschätzter Spread ist zu hoch.")
    max_by_position = portfolio_value * profile.max_position_pct
    maximum_risk = portfolio_value * profile.risk_per_trade_pct
    risk_per_share = entry_price - stop_loss
    quantity_by_risk = maximum_risk / risk_per_share
    quantity_by_value = min(max_by_position, available_cash) / entry_price
    quantity = max(min(quantity_by_risk, quantity_by_value), 0.0)
    quantity = float(int(quantity * 1000) / 1000)
    if quantity <= 0:
        return RiskDecision(False, 0, 0, 0, "Nicht genügend Kapital für eine Position.")
    value = quantity * entry_price
    risk = quantity * risk_per_share
    return RiskDecision(True, quantity, value, risk, "Risikoregeln erfüllt.")
