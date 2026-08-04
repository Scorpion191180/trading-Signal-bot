"""Technische Analyse und transparente Signalerzeugung."""

from .indicators import add_indicators
from .signals import SignalAction, SignalResult, analyze_signal

__all__ = ["SignalAction", "SignalResult", "add_indicators", "analyze_signal"]
