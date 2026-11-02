
"""Compare baseline and filtered backtest results."""

from dataclasses import dataclass

from tools.historical_simulator import SimulationResult


@dataclass(frozen=True)
class BacktestComparison:
    ticker: str
    baseline_return_pct: float
    filtered_return_pct: float
    return_improvement_pp: float
    baseline_drawdown_pct: float
    filtered_drawdown_pct: float
    drawdown_reduction_pp: float
    baseline_trades: int
    filtered_trades: int


def compare_backtests(
    ticker: str,
    baseline: SimulationResult,
    filtered: SimulationResult,
) -> BacktestComparison:
    """Compare two simulations using percentage-point differences."""

    if not ticker.strip():
        raise ValueError("Ticker must not be empty")

    return BacktestComparison(
        ticker=ticker,
        baseline_return_pct=baseline.total_return_pct,
        filtered_return_pct=filtered.total_return_pct,
        return_improvement_pp=(
            filtered.total_return_pct
            - baseline.total_return_pct
        ),
        baseline_drawdown_pct=baseline.max_drawdown_pct,
        filtered_drawdown_pct=filtered.max_drawdown_pct,
        drawdown_reduction_pp=(
            baseline.max_drawdown_pct
            - filtered.max_drawdown_pct
        ),
        baseline_trades=len(baseline.trades),
        filtered_trades=len(filtered.trades),
    )
