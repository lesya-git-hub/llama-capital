
import pytest
from tools.risk_manager import calculate_risk_plan
from tools.historical_simulator import simulate_long_only


def test_entry_executes_at_next_open():
    result = simulate_long_only(
        opens=[100, 110, 120, 130],
        entry_signals=[True, False, False, False],
        exit_signals=[False, True, False, False],
        initial_cash=1000,
        fee_rate=0,
        max_position_fraction=1.0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1

    trade = result.trades[0]

    assert trade.entry_price == 110
    assert trade.exit_price == 120
    assert trade.quantity == 9
    assert trade.net_pnl == pytest.approx(90)
    assert result.final_cash == pytest.approx(1090)


def test_signal_on_last_day_cannot_execute():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[False, False, True],
        exit_signals=[False, False, False],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 0
    assert result.final_cash == pytest.approx(1000)


def test_exit_executes_at_next_open():
    result = simulate_long_only(
        opens=[100, 110, 120, 90],
        entry_signals=[True, False, False, False],
        exit_signals=[False, False, True, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_price == 90
    assert result.trades[0].net_pnl == pytest.approx(-180)


def test_no_signals_preserves_cash():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[False] * 3,
        exit_signals=[False] * 3,
        initial_cash=1000,
    )

    assert result.trades == ()
    assert result.final_cash == pytest.approx(1000)


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[True, False],
            exit_signals=[False, False, False],
        )


def test_rejects_invalid_open_price():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, -110, 120],
            entry_signals=[True, False, False],
            exit_signals=[False, False, False],
        )


def test_rejects_non_boolean_signals():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[1, 0, 0],
            exit_signals=[False, False, False],
        )

def test_simulator_deducts_transaction_costs():
    result = simulate_long_only(
        opens=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, True, False],
        initial_cash=1000,
        fee_rate=0.001,
        max_position_fraction=1.0,
        slippage_rate=0.001,
    )

    assert len(result.trades) == 1
    assert result.trades[0].quantity == 9
    assert result.trades[0].net_pnl == pytest.approx(86.22009)
    assert result.final_cash == pytest.approx(1086.22009)


def test_simulator_handles_multiple_trades():
    result = simulate_long_only(
        opens=[100, 100, 110, 110, 120],
        entry_signals=[True, False, True, False, False],
        exit_signals=[False, True, False, True, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 2
    assert result.trades[0].net_pnl == pytest.approx(100)
    assert result.trades[1].net_pnl == pytest.approx(100)
    assert result.final_cash == pytest.approx(1200)


def test_exit_signal_without_position_is_ignored():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[False, False, False],
        exit_signals=[True, False, False],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.trades == ()
    assert result.final_cash == pytest.approx(1000)


def test_rejects_invalid_execution_cost():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[True, False, False],
            exit_signals=[False, False, False],
            slippage_rate=-0.01,
        )

def test_open_position_included_in_final_equity():
    result = simulate_long_only(
        opens=[100, 100, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 10
    assert result.final_cash == pytest.approx(0)
    assert result.final_equity == pytest.approx(1200)


def test_final_equity_includes_cash_and_shares():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 9
    assert result.final_cash == pytest.approx(10)
    assert result.final_equity == pytest.approx(1090)


def test_closed_position_final_equity_equals_cash():
    result = simulate_long_only(
        opens=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, True, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 0
    assert result.final_equity == pytest.approx(
        result.final_cash
    )


def test_no_trades_preserves_final_equity():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[False, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
    )

    assert result.open_quantity == 0
    assert result.final_equity == pytest.approx(1000)

def test_default_allocation_limits_position_to_20_percent():
    result = simulate_long_only(
        opens=[100, 100, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 2
    assert result.final_cash == pytest.approx(800)
    assert result.final_equity == pytest.approx(1040)


def test_custom_allocation_fraction():
    result = simulate_long_only(
        opens=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=0.50,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 5
    assert result.final_cash == pytest.approx(500)
    assert result.final_equity == pytest.approx(1050)


def test_rejects_invalid_allocation_fraction():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110],
            entry_signals=[True, False],
            exit_signals=[False, False],
            max_position_fraction=1.5,
        )

def test_atr_risk_plan_respects_both_limits():
    plan = calculate_risk_plan(
        capital=10_000,
        entry_price=100,
        atr=5,
        risk_fraction=0.01,
        max_position_fraction=0.20,
        atr_multiplier=1.5,
    )

    assert plan.stop_price == pytest.approx(92.5)
    assert plan.quantity == 13
    assert plan.position_value == pytest.approx(1300)
    assert plan.capital_at_risk == pytest.approx(97.5)

def test_atr_limits_simulator_position_size():
    result = simulate_long_only(
        opens=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 13
    assert result.final_cash == pytest.approx(8700)
    assert result.final_equity == pytest.approx(10130)


def test_larger_atr_reduces_position_size():
    common = dict(
        opens=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        fee_rate=0,
        slippage_rate=0,
    )

    low_volatility = simulate_long_only(
        **common,
        atr_values=[2, 2, 2],
    )

    high_volatility = simulate_long_only(
        **common,
        atr_values=[10, 10, 10],
    )

    assert low_volatility.open_quantity == 20
    assert high_volatility.open_quantity == 6


def test_rejects_mismatched_atr_length():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[True, False, False],
            exit_signals=[False, False, False],
            atr_values=[5, 5],
        )

def test_stop_loss_gap_exits_at_open_not_stop_price():
    result = simulate_long_only(
        opens=[100, 100, 90, 92],
        entry_signals=[True, False, False, False],
        exit_signals=[False, False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].entry_price == 100
    assert result.trades[0].exit_price == 90
    assert result.trades[0].quantity == 13
    assert result.trades[0].net_pnl == pytest.approx(-130)
    assert result.final_equity == pytest.approx(9870)

def test_gap_stop_includes_fees_and_slippage():
    result = simulate_long_only(
        opens=[100, 100, 90],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0.001,
        slippage_rate=0.001,
    )

    assert len(result.trades) == 1

    trade = result.trades[0]

    assert trade.quantity == 13
    assert trade.entry_price == 100
    assert trade.exit_price == 90

    assert trade.net_pnl == pytest.approx(-134.94013)
    assert result.final_equity == pytest.approx(
        10_000 + trade.net_pnl
    )

def test_intraday_low_triggers_stop_loss():
    result = simulate_long_only(
        opens=[100, 100, 101],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0,
        slippage_rate=0,
        lows=[99, 90, 99],
    )

    assert len(result.trades) == 1

    trade = result.trades[0]

    assert trade.entry_price == 100
    assert trade.exit_price == pytest.approx(92.5)
    assert trade.quantity == 13
    assert trade.net_pnl == pytest.approx(-97.5)
    assert result.open_quantity == 0
    assert result.final_equity == pytest.approx(9902.5)

def test_rejects_mismatched_low_prices():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[False, False, False],
            exit_signals=[False, False, False],
            lows=[99, 109],
        )


def test_rejects_low_above_open():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[False, False, False],
            exit_signals=[False, False, False],
            lows=[99, 115, 119],
        )


def test_rejects_negative_low_price():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            entry_signals=[False, False, False],
            exit_signals=[False, False, False],
            lows=[99, -5, 119],
        )

def test_opening_gap_takes_priority_over_intraday_stop():
    result = simulate_long_only(
        opens=[100, 100, 90],
        lows=[99, 99, 85],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1

    trade = result.trades[0]

    assert trade.entry_price == 100
    assert trade.exit_price == 90
    assert trade.quantity == 13
    assert trade.net_pnl == pytest.approx(-130)

    assert result.open_quantity == 0
    assert result.final_equity == pytest.approx(9870)

def test_reentry_after_intraday_stop():
    result = simulate_long_only(
        opens=[100, 100, 100, 100],
        lows=[99, 90, 99, 99],
        entry_signals=[True, True, False, False],
        exit_signals=[False, False, True, False],
        initial_cash=10_000,
        max_position_fraction=0.20,
        atr_values=[5, 5, 5, 5],
        risk_fraction=0.01,
        atr_multiplier=1.5,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 2

    first, second = result.trades

    assert first.entry_price == 100
    assert first.exit_price == pytest.approx(92.5)
    assert first.quantity == 13
    assert first.net_pnl == pytest.approx(-97.5)

    assert second.entry_price == 100
    assert second.exit_price == 100
    assert second.net_pnl == pytest.approx(0)

    assert result.open_quantity == 0
    assert result.final_equity == pytest.approx(9902.5)

def test_equity_curve_without_trades():
    result = simulate_long_only(
        opens=[100, 110, 120],
        entry_signals=[False, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
    )

    assert result.equity_curve == pytest.approx(
        (1000, 1000, 1000)
    )


def test_equity_curve_tracks_open_position():
    result = simulate_long_only(
        opens=[100, 100, 120, 110],
        entry_signals=[True, False, False, False],
        exit_signals=[False, False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.equity_curve == pytest.approx(
        (1000, 1000, 1200, 1100)
    )

    assert result.final_equity == pytest.approx(1100)


def test_equity_curve_tracks_realized_profit():
    result = simulate_long_only(
        opens=[100, 100, 110, 120],
        entry_signals=[True, False, False, False],
        exit_signals=[False, True, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.equity_curve == pytest.approx(
        (1000, 1000, 1100, 1100)
    )

    assert result.final_cash == pytest.approx(1100)
    assert result.final_equity == pytest.approx(1100)

def test_equity_curve_uses_closing_prices():
    result = simulate_long_only(
        opens=[100, 100, 100],
        closes=[100, 110, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity == 10
    assert result.equity_curve == pytest.approx(
        (1000, 1100, 1200)
    )
    assert result.final_equity == pytest.approx(1200)


def test_exit_still_executes_at_open_not_close():
    result = simulate_long_only(
        opens=[100, 100, 105],
        closes=[100, 110, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, True, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_price == 105
    assert result.final_equity == pytest.approx(1050)
    assert result.equity_curve == pytest.approx(
        (1000, 1100, 1050)
    )


def test_rejects_closing_price_below_low():
    with pytest.raises(ValueError):
        simulate_long_only(
            opens=[100, 110, 120],
            lows=[99, 105, 115],
            closes=[100, 104, 120],
            entry_signals=[False, False, False],
            exit_signals=[False, False, False],
        )

def test_simulator_calculates_max_drawdown():
    result = simulate_long_only(
        opens=[100, 100, 100, 100],
        closes=[100, 100, 90, 110],
        entry_signals=[True, False, False, False],
        exit_signals=[False, False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.equity_curve == pytest.approx(
        (1000, 1000, 900, 1100)
    )
    assert result.max_drawdown_pct == pytest.approx(10.0)


def test_simulator_drawdown_after_recovery():
    result = simulate_long_only(
        opens=[100, 100, 100, 100, 100],
        closes=[100, 100, 120, 90, 130],
        entry_signals=[True, False, False, False, False],
        exit_signals=[False, False, False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.equity_curve == pytest.approx(
        (1000, 1000, 1200, 900, 1300)
    )
    assert result.max_drawdown_pct == pytest.approx(25.0)


def test_simulator_no_trades_has_zero_drawdown():
    result = simulate_long_only(
        opens=[100, 110, 120],
        closes=[100, 105, 115],
        entry_signals=[False, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
    )

    assert result.max_drawdown_pct == pytest.approx(0.0)

def test_simulator_reports_positive_total_return():
    result = simulate_long_only(
        opens=[100, 100, 100],
        closes=[100, 110, 120],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.final_equity == pytest.approx(1200)
    assert result.total_return_pct == pytest.approx(20.0)


def test_simulator_reports_negative_total_return():
    result = simulate_long_only(
        opens=[100, 100, 100],
        closes=[100, 95, 80],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.final_equity == pytest.approx(800)
    assert result.total_return_pct == pytest.approx(-20.0)


def test_simulator_reports_zero_total_return_without_trades():
    result = simulate_long_only(
        opens=[100, 110, 120],
        closes=[100, 105, 115],
        entry_signals=[False, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
    )

    assert result.total_return_pct == pytest.approx(0.0)

def test_simulator_reports_annualized_return():
    result = simulate_long_only(
        opens=[100, 100, 100],
        closes=[100, 100, 110],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    expected = ((1.10 ** (252 / 2)) - 1) * 100

    assert result.annualized_return_pct == pytest.approx(
        expected
    )


def test_simulator_reports_annualized_volatility():
    result = simulate_long_only(
        opens=[100, 100, 100],
        closes=[100, 110, 99],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
        max_position_fraction=1.0,
        fee_rate=0,
        slippage_rate=0,
    )

    expected = (0.20 / (2 ** 0.5)) * (252 ** 0.5) * 100

    assert result.annualized_volatility_pct == pytest.approx(
        expected
    )


def test_simulator_flat_portfolio_has_zero_volatility():
    result = simulate_long_only(
        opens=[100, 110, 120],
        closes=[100, 105, 115],
        entry_signals=[False, False, False],
        exit_signals=[False, False, False],
        initial_cash=1000,
    )

    assert result.annualized_return_pct == pytest.approx(0.0)
    assert result.annualized_volatility_pct == pytest.approx(0.0)

def test_simulator_accepts_atr_warmup_none():
    result = simulate_long_only(
        opens=[100, 100, 100, 100],
        entry_signals=[False, False, True, False],
        exit_signals=[False] * 4,
        atr_values=[None, None, 2.0, 2.0],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert result.open_quantity > 0


def test_simulator_rejects_entry_without_atr():
    with pytest.raises(
        ValueError,
        match="Entry signal requires a valid ATR",
    ):
        simulate_long_only(
            opens=[100, 100, 100],
            entry_signals=[True, False, False],
            exit_signals=[False] * 3,
            atr_values=[None, 2.0, 2.0],
        )

def test_exit_reason_signal():
    result = simulate_long_only(
        opens=[100.0, 100.0, 110.0],
        entry_signals=[True, False, False],
        exit_signals=[False, True, False],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "signal"


def test_exit_reason_stop_gap():
    result = simulate_long_only(
        opens=[100.0, 100.0, 90.0],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        atr_values=[2.0, 2.0, 2.0],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_gap"
    assert result.trades[0].exit_price == pytest.approx(90.0)


def test_exit_reason_stop_intraday():
    result = simulate_long_only(
        opens=[100.0, 100.0, 100.0],
        lows=[100.0, 96.0, 100.0],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        atr_values=[2.0, 2.0, 2.0],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_intraday"
    assert result.trades[0].exit_price == pytest.approx(97.0)

def test_trade_records_next_open_execution_days():
    result = simulate_long_only(
        opens=[100.0, 101.0, 102.0, 103.0],
        entry_signals=[True, False, False, False],
        exit_signals=[False, True, False, False],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].entry_day == 1
    assert result.trades[0].exit_day == 2
    assert result.trades[0].exit_reason == "signal"


def test_trade_records_same_day_intraday_stop():
    result = simulate_long_only(
        opens=[100.0, 100.0, 100.0],
        lows=[100.0, 96.0, 100.0],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        atr_values=[2.0, 2.0, 2.0],
        initial_cash=1000,
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(result.trades) == 1
    assert result.trades[0].entry_day == 1
    assert result.trades[0].exit_day == 1
    assert result.trades[0].exit_reason == "stop_intraday"

def test_realized_trade_pnl_reconciles_with_final_cash():
    initial_cash = 10_000.0

    result = simulate_long_only(
        opens=[100, 100, 110, 110, 120],
        entry_signals=[True, False, True, False, False],
        exit_signals=[False, True, False, True, False],
        initial_cash=initial_cash,
        max_position_fraction=1.0,
        fee_rate=0.001,
        slippage_rate=0.001,
    )

    assert len(result.trades) == 2
    assert result.open_quantity == 0

    realized_pnl = sum(
        trade.net_pnl for trade in result.trades
    )

    assert result.final_cash == pytest.approx(
        initial_cash + realized_pnl
    )

    assert result.final_equity == pytest.approx(
        result.final_cash
    )
