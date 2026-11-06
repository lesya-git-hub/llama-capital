"""Offline software release checks; not certification of investment performance."""

from collections.abc import Sequence
from datetime import date
from math import isclose

from tools.historical_snapshot import FrozenModel, canonical_json, input_hash
from tools.portfolio_research import PortfolioExperiment, replay_portfolio_experiment


def validate_holdout_boundary(
    dates: Sequence[date], *, training_start: date, training_end: date,
    holdout_start: date, holdout_end: date, minimum_history: int = 200,
) -> tuple[int, int]:
    """Return [preceding signal row, exclusive evaluation end) for supplied dates.

    Boundaries are end-exclusive. This does not slice an experiment, reset
    holdings, certify exchange coverage, or turn prior observations into an
    untouched holdout. History includes the signal row before the first fill.
    """
    if any(type(d) is not date for d in (training_start, training_end, holdout_start, holdout_end)):
        raise ValueError("Boundaries must be plain dates")
    if not training_start < training_end <= holdout_start < holdout_end:
        raise ValueError("Training and holdout boundaries overlap or are invalid")
    if type(minimum_history) is not int or minimum_history < 1:
        raise ValueError("Minimum history must be a positive integer")
    if not dates or any(type(d) is not date for d in dates):
        raise ValueError("Session dates required")
    if any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError("Dates must be unique and increasing")
    eligible = [i for i, d in enumerate(dates) if holdout_start <= d < holdout_end]
    if not eligible:
        raise ValueError("No holdout sessions")
    first = eligible[0]
    if first < minimum_history:
        raise ValueError("Insufficient pre-holdout history or missing signal boundary")
    return first - 1, eligible[-1] + 1


class ReleaseGateResult(FrozenModel):
    schema_version: int = 1
    scope: str = "offline_software_invariants_only"
    experiment_sha256: str
    report_sha256: str
    checks: tuple[str, ...]


def check_portfolio_release_gate(
    experiment: PortfolioExperiment, *, expected_sha256: str,
) -> ReleaseGateResult:
    """Validate identity/provenance, repeat replay, then reconcile its report."""
    first = replay_portfolio_experiment(experiment, expected_sha256=expected_sha256)
    second = replay_portfolio_experiment(experiment, expected_sha256=expected_sha256)
    if canonical_json(first) != canonical_json(second):
        raise ValueError("Nondeterministic offline replay")

    def equal(actual, expected, label):
        if not isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError(f"Reconciliation failed: {label}")

    if first.ending_cash < -1e-8:
        raise ValueError("Negative ending cash")
    equal(first.starting_capital, experiment.parameters.initial_cash, "starting capital")
    equal(first.marked_holdings_value, sum(p.marked_value for p in first.open_positions), "holdings")
    equal(first.realized_pnl, sum(t.accounting.net_pnl for t in first.completed_trades), "realized P&L")
    equal(first.unrealized_pnl, sum(p.unrealized_pnl for p in first.open_positions), "unrealized P&L")
    for p in first.open_positions:
        equal(p.marked_value, p.quantity * p.closing_price, f"{p.ticker} mark")
        equal(p.unrealized_pnl, p.marked_value - p.entry_cost_basis, f"{p.ticker} cost basis")
    equal(first.ending_capital, first.ending_cash + first.marked_holdings_value, "cash plus holdings")
    equal(first.ending_capital, first.starting_capital + first.realized_pnl + first.unrealized_pnl, "P&L")
    dates = tuple(bar.date for bar in experiment.snapshot.tickers[0].bars)
    if tuple(point.date for point in first.equity_curve) != dates:
        raise ValueError("Equity calendar mismatch")
    equal(first.equity_curve[0].equity, first.starting_capital, "initial equity")
    equal(first.equity_curve[-1].equity, first.ending_capital, "final equity")
    if first.completed_trade_count != len(first.completed_trades):
        raise ValueError("Completed trade count mismatch")
    return ReleaseGateResult(
        experiment_sha256=expected_sha256, report_sha256=input_hash(first),
        checks=("snapshot_and_experiment_integrity", "execution_provenance",
                "calendar_and_currency_compatibility", "deterministic_replay",
                "final_cash_holdings_and_pnl_reconciliation"),
    )
