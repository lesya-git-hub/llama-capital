
from __future__ import annotations

from collections.abc import Sequence

from tools.market_indicators import (
    sma,
    rsi,
    atr,
    donchian_high,
    previous_average_volume,
)

from tools.quantitative_signals import (
    QuantitativeSignal,
    mean_reversion_signal,
    trend_breakout_signal,
)


def evaluate_mean_reversion(
    ticker: str,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> tuple[QuantitativeSignal, float]:
    """Evaluate mean reversion and return signal plus ATR."""

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("OHLC lengths must match")

    if len(closes) < 51:
        raise ValueError("At least 51 sessions required")

    current_sma = sma(closes, period=50)
    previous_rsi = rsi(closes[:-1], period=14)
    current_rsi = rsi(closes, period=14)
    current_atr = atr(highs, lows, closes, period=14)

    signal = mean_reversion_signal(
        ticker=ticker,
        close=closes[-1],
        sma50=current_sma,
        previous_rsi=previous_rsi,
        current_rsi=current_rsi,
    )

    return signal, current_atr


def evaluate_trend_breakout(
    ticker: str,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> tuple[QuantitativeSignal, float]:
    """Evaluate breakout and return signal plus ATR."""

    if not (
        len(highs) == len(lows) == len(closes) == len(volumes)
    ):
        raise ValueError("OHLCV lengths must match")

    if len(closes) < 21:
        raise ValueError("At least 21 sessions required")

    resistance = donchian_high(highs, period=20)
    average_volume = previous_average_volume(
        volumes, period=20
    )
    current_atr = atr(highs, lows, closes, period=14)

    signal = trend_breakout_signal(
        ticker=ticker,
        close=closes[-1],
        previous_high=resistance,
        volume=volumes[-1],
        average_volume=average_volume,
    )

    return signal, current_atr
