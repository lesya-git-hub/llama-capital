
import pytest

from tools.historical_simulator import simulate_long_only


def test_no_trades_means_zero_exposure():
    result = simulate_long_only(
        opens=[100, 100, 100, 100],
        entry_signals=[False] * 4,
        exit_signals=[False] * 4,
    )

    assert result.exposure_pct == 0.0


def test_position_held_for_two_sessions():
    result = simulate_long_only(
        opens=[100, 100, 100, 100],
        entry_signals=[True, False, False, False],
        exit_signals=[False, False, True, False],
    )

    assert result.exposure_pct == pytest.approx(100.0)


def test_same_day_stop_counts_as_exposure():
    result = simulate_long_only(
        opens=[100, 100, 100],
        lows=[100, 97, 100],
        closes=[100, 99, 100],
        entry_signals=[True, False, False],
        exit_signals=[False, False, False],
        atr_values=[1.0, 1.0, 1.0],
    )

    assert result.exposure_pct == pytest.approx(50.0)
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_intraday"
