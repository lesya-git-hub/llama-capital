
import math

import pytest

from tools.performance_metrics import calculate_sharpe_ratio


def test_positive_sharpe():
    result = calculate_sharpe_ratio(
        [100, 102, 101, 104, 103]
    )

    assert result is not None
    assert math.isfinite(result)
    assert result > 0


def test_flat_equity_has_undefined_sharpe():
    assert calculate_sharpe_ratio(
        [100, 100, 100, 100]
    ) is None


def test_risk_free_rate_reduces_sharpe():
    equity = [100, 102, 101, 104, 103]

    without_risk_free = calculate_sharpe_ratio(equity)
    with_risk_free = calculate_sharpe_ratio(
        equity,
        risk_free_rate=0.05,
    )

    assert without_risk_free is not None
    assert with_risk_free is not None
    assert with_risk_free < without_risk_free


def test_invalid_equity_rejected():
    with pytest.raises(ValueError):
        calculate_sharpe_ratio([100, 0, 105])


def test_insufficient_observations_rejected():
    with pytest.raises(ValueError):
        calculate_sharpe_ratio([100, 101])
