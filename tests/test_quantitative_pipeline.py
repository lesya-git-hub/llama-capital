
import pytest

from tools.quantitative_pipeline import (
    evaluate_mean_reversion,
    evaluate_trend_breakout,
)
from tools.quantitative_signals import SignalType


def make_candles(count=60):
    """Generate consistent synthetic OHLCV candles."""
    closes = [100.0] * count
    highs = [price + 2.0 for price in closes]
    lows = [price - 2.0 for price in closes]
    volumes = [1000.0] * count
    return highs, lows, closes, volumes


def test_mean_reversion_no_signal_on_flat_market():
    highs, lows, closes, _ = make_candles()

    signal, volatility = evaluate_mean_reversion(
        "TEST", highs, lows, closes
    )

    assert signal.strategy == SignalType.MEAN_REVERSION
    assert signal.triggered is False
    assert volatility == pytest.approx(4.0)


def test_breakout_detects_confirmed_signal():
    highs, lows, closes, volumes = make_candles()

    closes[-1] = 105.0
    highs[-1] = 107.0
    lows[-1] = 103.0
    volumes[-1] = 2000.0

    signal, volatility = evaluate_trend_breakout(
        "TEST", highs, lows, closes, volumes
    )

    assert signal.strategy == SignalType.TREND_BREAKOUT
    assert signal.triggered is True
    assert volatility > 0


def test_breakout_rejects_weak_volume():
    highs, lows, closes, volumes = make_candles()

    closes[-1] = 105.0
    highs[-1] = 107.0
    lows[-1] = 103.0
    volumes[-1] = 1200.0

    signal, _ = evaluate_trend_breakout(
        "TEST", highs, lows, closes, volumes
    )

    assert signal.triggered is False


def test_breakout_excludes_current_high():
    highs, lows, closes, volumes = make_candles()

    closes[-1] = 105.0
    highs[-1] = 150.0
    lows[-1] = 103.0
    volumes[-1] = 2000.0

    signal, _ = evaluate_trend_breakout(
        "TEST", highs, lows, closes, volumes
    )

    assert signal.triggered is True


def test_pipeline_rejects_mismatched_lengths():
    highs, lows, closes, volumes = make_candles()

    with pytest.raises(ValueError):
        evaluate_trend_breakout(
            "TEST",
            highs[:-1],
            lows,
            closes,
            volumes,
        )


def test_pipeline_rejects_short_history():
    highs, lows, closes, volumes = make_candles(10)

    with pytest.raises(ValueError):
        evaluate_mean_reversion(
            "TEST", highs, lows, closes
        )

    with pytest.raises(ValueError):
        evaluate_trend_breakout(
            "TEST", highs, lows, closes, volumes
        )

def test_mean_reversion_detects_rsi_recovery():
    # Long stable period followed by a sharp decline.
    # A small rebound should lift RSI above 30
    # while price remains below SMA50.
    closes = [100.0] * 45

    closes += [
        95.0,
        90.0,
        85.0,
        80.0,
        75.0,
        70.0,
        65.0,
        60.0,
        55.0,
        50.0,
        45.0,
        40.0,
        35.0,
        30.0,
        25.0,
        60.0,
    ]

    highs = [price + 2.0 for price in closes]
    lows = [price - 2.0 for price in closes]

    signal, volatility = evaluate_mean_reversion(
        "TEST", highs, lows, closes
    )

    assert signal.strategy == SignalType.MEAN_REVERSION
    assert signal.triggered is True
    assert volatility > 0
