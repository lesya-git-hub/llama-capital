
"""Tests for backtest comparison reporting."""

from dataclasses import replace

import pytest

from tools.backtest_comparison import (
    BacktestComparison,
    compare_backtests,
)
from tools.historical_simulator import SimulationResult


def make_result(
    total_return_pct: float,
    max_drawdown_pct: float,
) -> SimulationResult:
    """Create a minimal simulation result for reporting tests."""
    return SimulationResult(
        trades=(),
        final_cash=10_000.0,
        equity_curve=(10_000.0,),
        open_quantity=0,
        final_equity=10_000.0,
        max_drawdown_pct=max_drawdown_pct,
        total_return_pct=total_return_pct,
        annualized_return_pct=0.0,
        annualized_volatility_pct=0.0,
    )


def test_compare_backtests_calculates_improvements():
    baseline = make_result(
        total_return_pct=-3.67,
        max_drawdown_pct=4.60,
    )
    filtered = make_result(
        total_return_pct=0.14,
        max_drawdown_pct=0.87,
    )

    comparison = compare_backtests(
        ticker="JPM",
        baseline=baseline,
        filtered=filtered,
    )

    assert isinstance(comparison, BacktestComparison)
    assert comparison.ticker == "JPM"
    assert comparison.return_improvement_pp == pytest.approx(3.81)
    assert comparison.drawdown_reduction_pp == pytest.approx(3.73)
    assert comparison.baseline_trades == 0
    assert comparison.filtered_trades == 0


def test_compare_backtests_detects_worse_performance():
    baseline = make_result(1.88, 1.80)
    filtered = make_result(0.52, 1.48)

    comparison = compare_backtests("WMT", baseline, filtered)

    assert comparison.return_improvement_pp == pytest.approx(-1.36)
    assert comparison.drawdown_reduction_pp == pytest.approx(0.32)


def test_compare_backtests_rejects_empty_ticker():
    baseline = make_result(0.0, 0.0)

    with pytest.raises(ValueError, match="Ticker"):
        compare_backtests("   ", baseline, baseline)


def test_comparison_is_immutable():
    baseline = make_result(0.0, 0.0)
    comparison = compare_backtests("MSFT", baseline, baseline)

    with pytest.raises(AttributeError):
        comparison.ticker = "AAPL"
