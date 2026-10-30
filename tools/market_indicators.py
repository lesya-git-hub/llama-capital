
from __future__ import annotations

from collections.abc import Sequence
from math import isfinite


def sma(
    closes: Sequence[float],
    period: int = 50,
) -> float:
    """Calculate a simple moving average using completed sessions."""

    if period <= 0:
        raise ValueError("Period must be positive")

    if len(closes) < period:
        raise ValueError("Insufficient price history")

    window = closes[-period:]

    if any(not isfinite(price) or price <= 0 for price in window):
        raise ValueError("Prices must be finite and positive")

    return sum(window) / period

def rsi(
    closes: Sequence[float],
    period: int = 14,
) -> float:
    """Calculate RSI using Wilder's smoothing method."""

    if period <= 0:
        raise ValueError("Period must be positive")

    if len(closes) < period + 1:
        raise ValueError("Insufficient price history")

    if any(not isfinite(p) or p <= 0 for p in closes):
        raise ValueError("Prices must be finite and positive")

    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_gain == 0 and avg_loss == 0:
        return 50.0

    if avg_loss == 0:
        return 100.0

    if avg_gain == 0:
        return 0.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))

def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float:
    """Calculate Average True Range using Wilder's smoothing."""

    if period <= 0:
        raise ValueError("Period must be positive")

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("OHLC sequences must have equal lengths")

    if len(closes) < period + 1:
        raise ValueError("Insufficient price history")

    for high, low, close in zip(highs, lows, closes):
        if not all(isfinite(v) and v > 0 for v in (high, low, close)):
            raise ValueError("OHLC prices must be finite and positive")

        if low > high or not low <= close <= high:
            raise ValueError("Invalid OHLC candle")

    true_ranges = []

    for i in range(1, len(closes)):
        true_range = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(true_range)

    average_tr = sum(true_ranges[:period]) / period

    for tr in true_ranges[period:]:
        average_tr = (
            average_tr * (period - 1) + tr
        ) / period

    return average_tr


def donchian_high(
    highs: Sequence[float],
    period: int = 20,
) -> float:
    """Highest high of the previous N completed sessions.

    The final element is the current session and is excluded.
    """

    if period <= 0:
        raise ValueError("Period must be positive")

    if len(highs) < period + 1:
        raise ValueError("Insufficient price history")

    window = highs[-(period + 1):-1]

    if any(not isfinite(h) or h <= 0 for h in window):
        raise ValueError("High prices must be finite and positive")

    return max(window)

def previous_average_volume(
    volumes: Sequence[float],
    period: int = 20,
) -> float:
    """Average volume of previous N completed sessions.

    The final element represents the current session
    and is deliberately excluded.
    """

    if period <= 0:
        raise ValueError("Period must be positive")

    if len(volumes) < period + 1:
        raise ValueError("Insufficient volume history")

    window = volumes[-(period + 1):-1]

    if any(not isfinite(v) or v < 0 for v in window):
        raise ValueError("Volumes must be finite and non-negative")

    return sum(window) / period
