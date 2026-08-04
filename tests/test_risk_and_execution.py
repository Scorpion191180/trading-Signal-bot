from __future__ import annotations

import pytest

from src.config import STRATEGIES
from src.portfolio.execution import simulated_execution
from src.portfolio.risk import calculate_position_size


def test_position_size_respects_value_and_risk_limits():
    profile = STRATEGIES["Normal"]
    decision = calculate_position_size(
        portfolio_value=10_000,
        available_cash=10_000,
        entry_price=100,
        stop_loss=95,
        profile=profile,
        open_positions=0,
        relative_volume=1.2,
        data_is_fresh=True,
        spread_pct=0.001,
    )
    assert decision.allowed
    assert decision.position_value <= 10_000 * profile.max_position_pct
    assert decision.risk_amount <= 10_000 * profile.risk_per_trade_pct


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"data_is_fresh": False}, "veraltet"),
        ({"open_positions": 5}, "Maximale"),
        ({"relative_volume": 0.1}, "Volumen"),
        ({"spread_pct": 0.02}, "Spread"),
    ],
)
def test_protection_rules_block_trade(override, message):
    arguments = {
        "portfolio_value": 10_000,
        "available_cash": 10_000,
        "entry_price": 100,
        "stop_loss": 95,
        "profile": STRATEGIES["Normal"],
        "open_positions": 0,
        "relative_volume": 1.2,
        "data_is_fresh": True,
        "spread_pct": 0.001,
    }
    arguments.update(override)
    decision = calculate_position_size(**arguments)
    assert not decision.allowed
    assert message in decision.reason


def test_fee_spread_and_slippage_are_conservative():
    buy = simulated_execution("BUY", 100, 10, fee=1, spread_pct=0.002, slippage_pct=0.001)
    sell = simulated_execution("SELL", 100, 10, fee=1, spread_pct=0.002, slippage_pct=0.001)
    assert buy.execution_price == pytest.approx(100.2)
    assert sell.execution_price == pytest.approx(99.8)
    assert buy.fees == sell.fees == 1
    assert buy.spread_cost == pytest.approx(1.0)
    assert buy.slippage_cost == pytest.approx(1.0)
