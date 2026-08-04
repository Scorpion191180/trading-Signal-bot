"""Reproduzierbares Ausführungsmodell für ausschließlich virtuelle Orders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionQuote:
    side: str
    market_price: float
    execution_price: float
    quantity: float
    gross_value: float
    fees: float
    spread_cost: float
    slippage_cost: float


def simulated_execution(
    side: str,
    market_price: float,
    quantity: float,
    *,
    fee: float,
    spread_pct: float,
    slippage_pct: float,
) -> ExecutionQuote:
    """Simuliert eine konservative Market-Ausführung ohne späteren Kursumbau."""

    normalized_side = side.upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("Orderseite muss BUY oder SELL sein.")
    if market_price <= 0 or quantity <= 0:
        raise ValueError("Kurs und Stückzahl müssen positiv sein.")
    direction = 1 if normalized_side == "BUY" else -1
    spread_cost_per_unit = market_price * spread_pct / 2
    slippage_cost_per_unit = market_price * slippage_pct
    execution_price = market_price + direction * (spread_cost_per_unit + slippage_cost_per_unit)
    gross = execution_price * quantity
    return ExecutionQuote(
        side=normalized_side,
        market_price=market_price,
        execution_price=round(execution_price, 8),
        quantity=quantity,
        gross_value=round(gross, 8),
        fees=round(max(fee, 0.0), 8),
        spread_cost=round(spread_cost_per_unit * quantity, 8),
        slippage_cost=round(slippage_cost_per_unit * quantity, 8),
    )
