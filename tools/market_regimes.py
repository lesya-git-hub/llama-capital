
"""Classify market regimes using historical indicators."""

from __future__ import annotations

from enum import Enum
from collections.abc import Sequence
from math import isfinite

from tools.market_indicators import sma, atr


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"


def classify_market_regime(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volatility_threshold: float = 0.05,
) -> MarketRegime:
    """Classify the regime at the latest completed session."""

    if not (
        len(highs) == len(lows) == len(closes)
    ):
        raise ValueError("OHLC lengths must match")

    if len(closes) < 200:
        raise ValueError("At least 200 sessions required")

    if (
        not isfinite(volatility_threshold)
        or volatility_threshold <= 0
    ):
        raise ValueError("Invalid volatility threshold")

    sma50 = sma(closes, period=50)
    sma200 = sma(closes, period=200)

    current_atr = atr(
        highs=highs,
        lows=lows,
        closes=closes,
        period=14,
    )

    normalized_atr = current_atr / closes[-1]

    if normalized_atr > volatility_threshold:
        return MarketRegime.HIGH_VOLATILITY

    if closes[-1] > sma200 and sma50 > sma200:
        return MarketRegime.BULL

    if closes[-1] < sma200 and sma50 < sma200:
        return MarketRegime.BEAR

    return MarketRegime.SIDEWAYS

def generate_historical_regimes(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volatility_threshold: float = 0.05,
) -> list[MarketRegime | None]:
    """Generate regimes using only data available at each close."""

    n = len(closes)

    if not (len(highs) == len(lows) == n):
        raise ValueError("OHLC lengths must match")

    regimes: list[MarketRegime | None] = [None] * n

    for day in range(199, n):
        end = day + 1

        regimes[day] = classify_market_regime(
            highs=highs[:end],
            lows=lows[:end],
            closes=closes[:end],
            volatility_threshold=volatility_threshold,
        )

    return regimes

def filter_entries_by_regime(
    entries: Sequence[bool],
    regimes: Sequence[MarketRegime | None],
    excluded_regimes: set[MarketRegime],
) -> list[bool]:
    """Remove entry signals occurring in excluded market regimes."""

    if len(entries) != len(regimes):
        raise ValueError("Entries and regimes lengths must match")

    return [
        bool(entry) and regime not in excluded_regimes
        for entry, regime in zip(entries, regimes)
    ]
