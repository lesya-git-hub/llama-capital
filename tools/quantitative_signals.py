from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SignalType(str, Enum):
    MEAN_REVERSION = "mean_reversion"
    TREND_BREAKOUT = "trend_breakout"


@dataclass(frozen=True)
class QuantitativeSignal:
    ticker: str
    strategy: SignalType
    triggered: bool
    reason: str


def mean_reversion_signal(
    ticker: str,
    close: float,
    sma50: float,
    previous_rsi: float,
    current_rsi: float,
) -> QuantitativeSignal:
    """Detect a recovery setup below SMA50."""

    if sma50 <= 0:
        raise ValueError("SMA50 must be positive")

    discounted = close <= 0.95 * sma50

    rsi_recovery = (
        previous_rsi < 30
        and current_rsi >= 30
    )

    triggered = discounted and rsi_recovery

    return QuantitativeSignal(
        ticker=ticker,
        strategy=SignalType.MEAN_REVERSION,
        triggered=triggered,
        reason=(
            "Price below SMA50 with RSI recovery"
            if triggered
            else "Mean reversion conditions not met"
        ),
    )


def trend_breakout_signal(
    ticker: str,
    close: float,
    previous_high: float,
    volume: float,
    average_volume: float,
) -> QuantitativeSignal:
    """Detect a confirmed breakout above resistance."""

    if previous_high <= 0:
        raise ValueError("Previous high must be positive")

    if average_volume <= 0:
        raise ValueError("Average volume must be positive")

    price_breakout = close > previous_high

    volume_confirmed = (
        volume > 1.5 * average_volume
    )

    triggered = price_breakout and volume_confirmed

    return QuantitativeSignal(
        ticker=ticker,
        strategy=SignalType.TREND_BREAKOUT,
        triggered=triggered,
        reason=(
            "20-session breakout confirmed by volume"
            if triggered
            else "Breakout conditions not met"
        ),
    )