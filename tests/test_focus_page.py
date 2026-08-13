from __future__ import annotations

from datetime import UTC, datetime

from src.focus.analysis import FocusPosition
from src.focus.page import _signal_mode_text
from src.focus.quote import LiveQuote


def _quote(price: float = 18.3) -> LiveQuote:
    return LiveQuote(
        provider="Lang & Schwarz",
        venue="Lang & Schwarz",
        isin="US26740W1099",
        bid=price,
        ask=price,
        bid_size=None,
        ask_size=None,
        last=price,
        high=price,
        low=price,
        change_percent=0.0,
        volume=1000,
        fetched_at=datetime(2026, 8, 13, 18, 0, tzinfo=UTC),
        refresh_seconds=10,
    )


def test_signal_mode_explains_buy_and_add_modes():
    assert "KAUFEN" in _signal_mode_text(FocusPosition(), _quote())

    losing_position = FocusPosition(invested=True, average_price=21.96, quantity=67.5)
    explanation = _signal_mode_text(losing_position, _quote())

    assert "NACHKAUFEN" in explanation
    assert "unter deinem Einstand" in explanation
    assert "Verbilligen" in explanation
