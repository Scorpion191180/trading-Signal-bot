from __future__ import annotations

import pandas as pd

from src.analysis.signals import SignalAction, analyze_signal
from src.config import STRATEGIES, WEIGHTS


def test_score_is_transparent_and_within_range(market_frame):
    result = analyze_signal("TEST", market_frame, STRATEGIES["Normal"], provider="test")
    assert result.action in {SignalAction.BUY, SignalAction.HOLD, SignalAction.SELL}
    assert 0 <= result.score <= 100
    assert round(sum(result.components.values()), 2) == result.score
    assert set(result.components) == set(WEIGHTS.as_dict())
    assert result.stop_loss < result.price < result.target_1
    assert result.reward_risk >= STRATEGIES["Normal"].minimum_reward_risk
    assert result.experimental is True


def test_stale_data_blocks_signal(market_frame):
    stale = market_frame.copy()
    stale.index = pd.date_range("2020-01-01", periods=len(stale), freq="5min", tz="UTC")
    result = analyze_signal("OLD", stale, STRATEGIES["Normal"], provider="test", stale_after_minutes=10)
    assert result.action is SignalAction.BLOCKED
    assert "veraltet" in (result.data_problem or "")


def test_missing_volume_blocks_signal(market_frame):
    market_frame.loc[market_frame.index[-1], "volume"] = 0
    result = analyze_signal("NOVOL", market_frame, STRATEGIES["Normal"], provider="test")
    assert result.action is SignalAction.BLOCKED
    assert "Volumen" in (result.data_problem or "")


def test_insufficient_history_blocks_signal(market_frame):
    result = analyze_signal("SHORT", market_frame.head(20), STRATEGIES["Normal"], provider="test")
    assert result.action is SignalAction.BLOCKED
