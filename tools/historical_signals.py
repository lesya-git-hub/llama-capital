
"""Generate historical trading signals without future data."""

from collections.abc import Sequence
from tools.market_indicators import sma
from tools.quantitative_pipeline import (
    evaluate_mean_reversion,
    evaluate_trend_breakout,
)


def generate_historical_signals(
    ticker: str,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    strategy: str,
) -> tuple[list[bool], list[float | None]]:
    """Generate daily entry signals and ATR values.

    Each day's calculation uses data available
    through that day's close only.
    """

    n = len(closes)

    if not (
        len(highs) == len(lows) == len(volumes) == n
    ):
        raise ValueError("OHLCV lengths must match")

    if strategy == "mean_reversion":
        evaluator = evaluate_mean_reversion
        minimum_history = 51

    elif strategy == "trend_breakout":
        evaluator = evaluate_trend_breakout
        minimum_history = 21

    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    signals = [False] * n
    atr_values: list[float | None] = [None] * n

    for day in range(minimum_history - 1, n):
        history_end = day + 1

        if strategy == "mean_reversion":
            signal, current_atr = evaluator(
                ticker=ticker,
                highs=highs[:history_end],
                lows=lows[:history_end],
                closes=closes[:history_end],
            )
        else:
            signal, current_atr = evaluator(
                ticker=ticker,
                highs=highs[:history_end],
                lows=lows[:history_end],
                closes=closes[:history_end],
                volumes=volumes[:history_end],
            )

        signals[day] = signal.triggered
        atr_values[day] = current_atr

    return signals, atr_values

def generate_mean_reversion_exits(
    closes: Sequence[float],
) -> list[bool]:
    """Generate close-based mean-reversion exit signals.

    A signal at index t is intended for execution
    at the opening price of session t+1.
    """

    exits = [False] * len(closes)

    for day in range(49, len(closes)):
        history = closes[:day + 1]

        current_sma = sma(history, period=50)

        exits[day] = closes[day] >= current_sma

    return exits
