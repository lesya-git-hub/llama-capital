
import pytest

from tools.portfolio_risk import (
    PortfolioState,
    approve_trade,
)
from tools.risk_manager import calculate_risk_plan


def make_portfolio(
    equity=5000,
    available_cash=2000,
    invested_value=3000,
    open_risk=100,
):
    return PortfolioState(
        equity=equity,
        available_cash=available_cash,
        invested_value=invested_value,
        open_risk=open_risk,
    )


def make_plan():
    return calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=4,
    )


def test_approves_trade_within_limits():
    decision = approve_trade(make_portfolio(), make_plan())

    assert decision.approved is True
    assert decision.reason == "Trade approved"


def test_rejects_insufficient_cash():
    portfolio = make_portfolio(available_cash=500)

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is False
    assert decision.reason == "Insufficient cash"


def test_rejects_excessive_exposure():
    portfolio = make_portfolio(
        available_cash=1500,
        invested_value=3500,
    )

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is False
    assert decision.reason == "Portfolio exposure limit exceeded"


def test_rejects_excessive_portfolio_risk():
    portfolio = make_portfolio(open_risk=220)

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is False
    assert decision.reason == "Portfolio risk limit exceeded"


def test_approves_exact_exposure_boundary():
    portfolio = make_portfolio(
        available_cash=1800,
        invested_value=3200,
    )

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is True


def test_rejects_zero_share_trade():
    plan = calculate_risk_plan(
        capital=1000,
        entry_price=500,
        atr=10,
    )

    decision = approve_trade(make_portfolio(), plan)

    assert decision.approved is False
    assert decision.reason == "Zero-share trade"


def test_rejects_invalid_portfolio_equity():
    portfolio = make_portfolio(equity=0)

    with pytest.raises(ValueError):
        approve_trade(portfolio, make_plan())


def test_rejects_negative_cash():
    portfolio = make_portfolio(available_cash=-100)

    with pytest.raises(ValueError):
        approve_trade(portfolio, make_plan())


def test_rejects_invalid_exposure_limit():
    with pytest.raises(ValueError):
        approve_trade(
            make_portfolio(),
            make_plan(),
            max_total_exposure=1.5,
        )


def test_rejects_non_finite_portfolio_value():
    portfolio = make_portfolio(open_risk=float("nan"))

    with pytest.raises(ValueError):
        approve_trade(portfolio, make_plan())

def test_approves_exact_risk_boundary():
    # Equity €5,000, maximum risk 5% = €250.
    # Existing risk €202 + new risk €48 = €250.
    portfolio = make_portfolio(open_risk=202)

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is True


def test_rejects_risk_above_boundary():
    # €203 + €48 = €251, exceeding the €250 limit.
    portfolio = make_portfolio(open_risk=203)

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is False
    assert decision.reason == "Portfolio risk limit exceeded"


def test_rejects_exposure_above_boundary():
    # €3,201 + €800 = €4,001, exceeding 80% of equity.
    portfolio = make_portfolio(
        available_cash=1799,
        invested_value=3201,
    )

    decision = approve_trade(portfolio, make_plan())

    assert decision.approved is False
    assert decision.reason == "Portfolio exposure limit exceeded"
