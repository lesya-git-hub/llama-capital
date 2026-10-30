
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from tools.risk_manager import RiskPlan


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    available_cash: float
    invested_value: float
    open_risk: float


@dataclass(frozen=True)
class PortfolioDecision:
    approved: bool
    reason: str


def approve_trade(
    portfolio: PortfolioState,
    plan: RiskPlan,
    max_total_exposure: float = 0.80,
    max_total_risk: float = 0.05,
) -> PortfolioDecision:
    """Approve a long trade against portfolio-level limits."""

    values = (
        portfolio.equity,
        portfolio.available_cash,
        portfolio.invested_value,
        portfolio.open_risk,
        plan.position_value,
        plan.capital_at_risk,
        max_total_exposure,
        max_total_risk,
    )

    if any(not isfinite(value) for value in values):
        raise ValueError("All portfolio inputs must be finite")

    if portfolio.equity <= 0:
        raise ValueError("Portfolio equity must be positive")

    if any(
        value < 0
        for value in (
            portfolio.available_cash,
            portfolio.invested_value,
            portfolio.open_risk,
            plan.position_value,
            plan.capital_at_risk,
        )
    ):
        raise ValueError("Portfolio values cannot be negative")

    if not 0 < max_total_exposure <= 1:
        raise ValueError("Invalid exposure limit")

    if not 0 < max_total_risk <= 1:
        raise ValueError("Invalid risk limit")

    if plan.quantity <= 0:
        return PortfolioDecision(False, "Zero-share trade")

    if plan.position_value > portfolio.available_cash:
        return PortfolioDecision(False, "Insufficient cash")

    projected_exposure = (
        portfolio.invested_value + plan.position_value
    ) / portfolio.equity

    if projected_exposure > max_total_exposure:
        return PortfolioDecision(
            False, "Portfolio exposure limit exceeded"
        )

    projected_risk = (
        portfolio.open_risk + plan.capital_at_risk
    ) / portfolio.equity

    if projected_risk > max_total_risk:
        return PortfolioDecision(
            False, "Portfolio risk limit exceeded"
        )

    return PortfolioDecision(True, "Trade approved")
