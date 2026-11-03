
import pytest

from tools.backtesting import BacktestTrade
from tools.trade_metrics import (
    calculate_trade_expectancy,
    calculate_trade_expectancy_pct,
)


def make_trade(net_pnl, return_pct):
    return BacktestTrade(
        entry_price=100.0,
        exit_price=110.0,
        quantity=10,
        gross_pnl=100.0,
        costs=0.0,
        net_pnl=net_pnl,
        return_pct=return_pct,
    )


def test_positive_trade_expectancy():
    trades = [
        make_trade(100.0, 10.0),
        make_trade(-40.0, -4.0),
        make_trade(60.0, 6.0),
    ]

    assert calculate_trade_expectancy(trades) == pytest.approx(40.0)


def test_percentage_expectancy():
    trades = [
        make_trade(100.0, 10.0),
        make_trade(-40.0, -4.0),
        make_trade(60.0, 6.0),
    ]

    assert calculate_trade_expectancy_pct(trades) == pytest.approx(4.0)


def test_no_completed_trades():
    assert calculate_trade_expectancy([]) is None
    assert calculate_trade_expectancy_pct([]) is None


def test_negative_expectancy():
    trades = [
        make_trade(-100.0, -10.0),
        make_trade(40.0, 4.0),
    ]

    assert calculate_trade_expectancy(trades) == pytest.approx(-30.0)
    assert calculate_trade_expectancy_pct(trades) == pytest.approx(-3.0)
