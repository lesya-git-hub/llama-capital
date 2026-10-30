
import pytest

from tools.performance_metrics import (
    calculate_max_drawdown,
    calculate_total_return,
    calculate_annualized_return,
    calculate_annualized_volatility,
)


def test_max_drawdown_with_recovery():
    equity = [10000, 11000, 12000, 10500, 9000, 11500]

    assert calculate_max_drawdown(equity) == pytest.approx(25.0)


def test_no_drawdown_for_rising_equity():
    equity = [10000, 10500, 11000, 12000]

    assert calculate_max_drawdown(equity) == pytest.approx(0.0)


def test_drawdown_for_falling_equity():
    equity = [10000, 9000, 8000]

    assert calculate_max_drawdown(equity) == pytest.approx(20.0)


def test_rejects_empty_equity_curve():
    with pytest.raises(ValueError):
        calculate_max_drawdown([])


def test_rejects_invalid_equity_value():
    with pytest.raises(ValueError):
        calculate_max_drawdown([10000, 0, 9000])

def test_total_return_profit():
    assert calculate_total_return(
        [10000, 10500, 11500]
    ) == pytest.approx(15.0)


def test_total_return_loss():
    assert calculate_total_return(
        [10000, 9500, 8000]
    ) == pytest.approx(-20.0)


def test_total_return_flat():
    assert calculate_total_return(
        [10000, 10000, 10000]
    ) == pytest.approx(0.0)


def test_total_return_rejects_empty_curve():
    with pytest.raises(ValueError):
        calculate_total_return([])

def test_annualized_return_one_year():
    equity = [10000] * 252 + [11000]

    assert calculate_annualized_return(equity) == pytest.approx(10.0)


def test_annualized_return_half_year():
    equity = [10000] * 126 + [11000]

    expected = ((1.10 ** 2) - 1) * 100

    assert calculate_annualized_return(equity) == pytest.approx(expected)


def test_annualized_return_flat():
    assert calculate_annualized_return(
        [10000, 10000, 10000]
    ) == pytest.approx(0.0)


def test_annualized_return_requires_two_observations():
    with pytest.raises(ValueError):
        calculate_annualized_return([10000])

def test_volatility_flat_equity():
    equity = [10000, 10000, 10000, 10000]

    assert calculate_annualized_volatility(
        equity
    ) == pytest.approx(0.0)


def test_volatility_known_returns():
    # Two returns: +10% and -10%.
    equity = [100, 110, 99]

    expected = (0.20 / (2 ** 0.5)) * (252 ** 0.5) * 100

    assert calculate_annualized_volatility(
        equity
    ) == pytest.approx(expected)


def test_volatility_rejects_short_curve():
    with pytest.raises(ValueError):
        calculate_annualized_volatility([10000, 11000])


def test_volatility_rejects_invalid_equity():
    with pytest.raises(ValueError):
        calculate_annualized_volatility(
            [10000, float("nan"), 11000]
        )
