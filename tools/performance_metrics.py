
from __future__ import annotations

from collections.abc import Sequence
from math import isfinite, sqrt


def calculate_max_drawdown(
    equity_curve: Sequence[float],
) -> float:
    """Return maximum peak-to-trough drawdown as a percentage.

    Example: 25.0 means a 25% maximum drawdown.
    """

    if not equity_curve:
        raise ValueError("Equity curve cannot be empty")

    if any(
        not isfinite(value) or value <= 0
        for value in equity_curve
    ):
        raise ValueError(
            "Equity values must be finite and positive"
        )

    peak = equity_curve[0]
    max_drawdown = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)

        drawdown = (peak - equity) / peak * 100

        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown

def calculate_total_return(
    equity_curve: Sequence[float],
) -> float:
    """Calculate total portfolio return as a percentage."""

    if not equity_curve:
        raise ValueError("Equity curve cannot be empty")

    if any(
        not isfinite(value) or value <= 0
        for value in equity_curve
    ):
        raise ValueError(
            "Equity values must be finite and positive"
        )

    initial_equity = equity_curve[0]
    final_equity = equity_curve[-1]

    return (
        (final_equity / initial_equity) - 1
    ) * 100

def calculate_annualized_return(
    equity_curve: Sequence[float],
    periods_per_year: int = 252,
) -> float:
    """Return annualized compounded growth in percent."""

    if len(equity_curve) < 2:
        raise ValueError("At least two equity observations required")

    if any(
        not isfinite(value) or value <= 0
        for value in equity_curve
    ):
        raise ValueError("Equity values must be finite and positive")

    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, int)
        or periods_per_year <= 0
    ):
        raise ValueError("Periods per year must be a positive integer")

    elapsed_periods = len(equity_curve) - 1
    growth_factor = equity_curve[-1] / equity_curve[0]

    return (
        growth_factor ** (periods_per_year / elapsed_periods) - 1
    ) * 100

def calculate_annualized_volatility(
    equity_curve: Sequence[float],
    periods_per_year: int = 252,
) -> float:
    """Return annualized sample volatility as a percentage."""

    if len(equity_curve) < 3:
        raise ValueError(
            "At least three equity observations required"
        )

    if any(
        not isfinite(value) or value <= 0
        for value in equity_curve
    ):
        raise ValueError(
            "Equity values must be finite and positive"
        )

    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, int)
        or periods_per_year <= 0
    ):
        raise ValueError(
            "Periods per year must be a positive integer"
        )

    returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
    ]

    mean_return = sum(returns) / len(returns)

    variance = sum(
        (r - mean_return) ** 2 for r in returns
    ) / (len(returns) - 1)

    return sqrt(variance * periods_per_year) * 100
