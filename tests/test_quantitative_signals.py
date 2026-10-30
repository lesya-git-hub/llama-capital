
import pytest

from tools.quantitative_signals import (
    SignalType,
    mean_reversion_signal,
    trend_breakout_signal,
)


def test_mean_reversion_triggers_on_rsi_recovery():
    signal = mean_reversion_signal(
        ticker="TEST",
        close=94,
        sma50=100,
        previous_rsi=28,
        current_rsi=32,
    )

    assert signal.triggered is True
    assert signal.strategy == SignalType.MEAN_REVERSION


def test_mean_reversion_rejects_falling_rsi():
    signal = mean_reversion_signal(
        ticker="TEST",
        close=94,
        sma50=100,
        previous_rsi=25,
        current_rsi=27,
    )

    assert signal.triggered is False


def test_mean_reversion_rejects_insufficient_discount():
    signal = mean_reversion_signal(
        ticker="TEST",
        close=98,
        sma50=100,
        previous_rsi=28,
        current_rsi=32,
    )

    assert signal.triggered is False


def test_breakout_triggers_with_volume_confirmation():
    signal = trend_breakout_signal(
        ticker="TEST",
        close=105,
        previous_high=100,
        volume=1600,
        average_volume=1000,
    )

    assert signal.triggered is True
    assert signal.strategy == SignalType.TREND_BREAKOUT


def test_breakout_rejects_weak_volume():
    signal = trend_breakout_signal(
        ticker="TEST",
        close=105,
        previous_high=100,
        volume=1100,
        average_volume=1000,
    )

    assert signal.triggered is False


def test_breakout_rejects_price_below_resistance():
    signal = trend_breakout_signal(
        ticker="TEST",
        close=99,
        previous_high=100,
        volume=2000,
        average_volume=1000,
    )

    assert signal.triggered is False


def test_invalid_sma_raises_error():
    with pytest.raises(ValueError):
        mean_reversion_signal(
            ticker="TEST",
            close=94,
            sma50=0,
            previous_rsi=28,
            current_rsi=32,
        )


def test_invalid_average_volume_raises_error():
    with pytest.raises(ValueError):
        trend_breakout_signal(
            ticker="TEST",
            close=105,
            previous_high=100,
            volume=1600,
            average_volume=0,
        )
def test_mean_reversion_triggers_at_exact_discount():
    signal = mean_reversion_signal(
        ticker="TEST",
        close=95,
        sma50=100,
        previous_rsi=29,
        current_rsi=30,
    )

    assert signal.triggered is True


def test_breakout_requires_price_above_previous_high():
    signal = trend_breakout_signal(
        ticker="TEST",
        close=100,
        previous_high=100,
        volume=2000,
        average_volume=1000,
    )

    assert signal.triggered is False


def test_breakout_requires_volume_above_threshold():
    signal = trend_breakout_signal(
        ticker="TEST",
        close=105,
        previous_high=100,
        volume=1500,
        average_volume=1000,
    )

    assert signal.triggered is False