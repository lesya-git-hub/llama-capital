
import pytest

from tools.risk_manager import calculate_risk_plan


def test_standard_risk_plan():
    plan = calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=4,
    )

    assert plan.stop_price == pytest.approx(94.0)
    assert plan.quantity == 8
    assert plan.position_value == pytest.approx(800.0)
    assert plan.capital_at_risk == pytest.approx(48.0)


def test_position_cap_limits_quantity():
    plan = calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=1,
    )

    assert plan.quantity == 10
    assert plan.position_value == pytest.approx(1000.0)


def test_risk_budget_limits_quantity():
    plan = calculate_risk_plan(
        capital=10000,
        entry_price=50,
        atr=10,
    )

    assert plan.quantity == 6
    assert plan.capital_at_risk == pytest.approx(90.0)


def test_zero_quantity_when_trade_too_expensive():
    plan = calculate_risk_plan(
        capital=1000,
        entry_price=500,
        atr=10,
    )

    assert plan.quantity == 0
    assert plan.position_value == 0
    assert plan.capital_at_risk == 0


def test_rejects_invalid_atr():
    with pytest.raises(ValueError):
        calculate_risk_plan(
            capital=5000,
            entry_price=100,
            atr=0,
        )


def test_rejects_stop_below_zero():
    with pytest.raises(ValueError):
        calculate_risk_plan(
            capital=5000,
            entry_price=100,
            atr=100,
        )


def test_rejects_invalid_risk_fraction():
    with pytest.raises(ValueError):
        calculate_risk_plan(
            capital=5000,
            entry_price=100,
            atr=4,
            risk_fraction=1.5,
        )


def test_rejects_non_finite_input():
    with pytest.raises(ValueError):
        calculate_risk_plan(
            capital=float("nan"),
            entry_price=100,
            atr=4,
        )

def test_fractional_shares_are_not_rounded_up():
    plan = calculate_risk_plan(
        capital=1000,
        entry_price=33,
        atr=2,
        max_position_fraction=0.10,
    )

    assert plan.quantity == 3
    assert plan.position_value == pytest.approx(99.0)


def test_risk_never_exceeds_budget():
    plan = calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=4,
        risk_fraction=0.01,
    )

    assert plan.capital_at_risk <= 50.0


def test_position_never_exceeds_cap():
    plan = calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=1,
        max_position_fraction=0.20,
    )

    assert plan.position_value <= 1000.0


def test_custom_atr_multiplier():
    plan = calculate_risk_plan(
        capital=5000,
        entry_price=100,
        atr=4,
        atr_multiplier=2.0,
    )

    assert plan.stop_price == pytest.approx(92.0)
    assert plan.capital_at_risk == pytest.approx(
        plan.quantity * 8.0
    )


def test_rejects_zero_capital():
    with pytest.raises(ValueError):
        calculate_risk_plan(
            capital=0,
            entry_price=100,
            atr=4,
        )
