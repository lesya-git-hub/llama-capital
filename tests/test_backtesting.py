
import pytest

from tools.backtesting import (
    calculate_trade_result,
    calculate_win_rate,
)


def test_profitable_trade_without_costs():
    trade = calculate_trade_result(
        entry_price=100,
        exit_price=110,
        quantity=10,
        fee_rate=0,
        slippage_rate=0,
    )

    assert trade.gross_pnl == pytest.approx(100)
    assert trade.costs == pytest.approx(0)
    assert trade.net_pnl == pytest.approx(100)
    assert trade.return_pct == pytest.approx(10)


def test_profitable_trade_with_costs():
    trade = calculate_trade_result(
        entry_price=100,
        exit_price=110,
        quantity=10,
    )

    assert trade.gross_pnl == pytest.approx(100)
    assert trade.costs == pytest.approx(4.1999)
    assert trade.net_pnl == pytest.approx(95.8001)


def test_losing_trade():
    trade = calculate_trade_result(
        entry_price=100,
        exit_price=90,
        quantity=10,
        fee_rate=0,
        slippage_rate=0,
    )

    assert trade.net_pnl == pytest.approx(-100)
    assert trade.return_pct == pytest.approx(-10)


def test_flat_trade_loses_money_after_costs():
    trade = calculate_trade_result(
        entry_price=100,
        exit_price=100,
        quantity=10,
    )

    assert trade.gross_pnl == pytest.approx(0)
    assert trade.net_pnl < 0


def test_win_rate():
    trades = [
        calculate_trade_result(100, 110, 1, 0, 0),
        calculate_trade_result(100, 90, 1, 0, 0),
        calculate_trade_result(100, 120, 1, 0, 0),
    ]

    assert calculate_win_rate(trades) == pytest.approx(
        66.6666666667
    )


def test_empty_win_rate():
    assert calculate_win_rate([]) == 0.0


def test_rejects_zero_quantity():
    with pytest.raises(ValueError):
        calculate_trade_result(100, 110, 0)


def test_rejects_invalid_fee():
    with pytest.raises(ValueError):
        calculate_trade_result(
            100, 110, 1, fee_rate=-0.01
        )


def test_rejects_non_finite_price():
    with pytest.raises(ValueError):
        calculate_trade_result(
            float("nan"), 110, 1
        )

def test_rejects_fractional_quantity():
    with pytest.raises(ValueError):
        calculate_trade_result(
            entry_price=100,
            exit_price=110,
            quantity=1.5,
        )


def test_rejects_boolean_quantity():
    with pytest.raises(ValueError):
        calculate_trade_result(
            entry_price=100,
            exit_price=110,
            quantity=True,
        )


def test_rejects_slippage_above_limit():
    with pytest.raises(ValueError):
        calculate_trade_result(
            entry_price=100,
            exit_price=110,
            quantity=10,
            slippage_rate=1.0,
        )


def test_rejects_negative_exit_price():
    with pytest.raises(ValueError):
        calculate_trade_result(
            entry_price=100,
            exit_price=-10,
            quantity=10,
        )


def test_flat_trade_is_not_a_win():
    trade = calculate_trade_result(
        entry_price=100,
        exit_price=100,
        quantity=10,
    )

    assert calculate_win_rate([trade]) == 0.0
