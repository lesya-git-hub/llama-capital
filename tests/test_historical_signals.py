
import pytest

from tools.historical_signals import generate_historical_signals, generate_mean_reversion_exits
from tools.quantitative_signals import QuantitativeSignal, SignalType
from tools.market_indicators import (
    donchian_high,
    previous_average_volume,
)


@pytest.mark.parametrize(
    "strategy,minimum_history,signal_type",
    [
        ("mean_reversion", 51, SignalType.MEAN_REVERSION),
        ("trend_breakout", 21, SignalType.TREND_BREAKOUT),
    ],
)
def test_historical_signals_use_only_available_history(
    monkeypatch,
    strategy,
    minimum_history,
    signal_type,
):
    observed_lengths = []

    def fake_evaluator(**kwargs):
        history_length = len(kwargs["closes"])
        observed_lengths.append(history_length)

        assert len(kwargs["highs"]) == history_length
        assert len(kwargs["lows"]) == history_length

        if "volumes" in kwargs:
            assert len(kwargs["volumes"]) == history_length

        signal = QuantitativeSignal(
            ticker=kwargs["ticker"],
            strategy=signal_type,
            triggered=True,
            reason="Synthetic test signal",
        )

        return signal, 2.0

    function_name = (
        "evaluate_mean_reversion"
        if strategy == "mean_reversion"
        else "evaluate_trend_breakout"
    )

    monkeypatch.setattr(
        f"tools.historical_signals.{function_name}",
        fake_evaluator,
    )

    n = minimum_history + 3

    signals, atr_values = generate_historical_signals(
        ticker="MSFT",
        highs=[110.0] * n,
        lows=[90.0] * n,
        closes=[100.0] * n,
        volumes=[1000.0] * n,
        strategy=strategy,
    )

    assert observed_lengths == list(
        range(minimum_history, n + 1)
    )

    assert signals[:minimum_history - 1] == [
        False
    ] * (minimum_history - 1)

    assert atr_values[:minimum_history - 1] == [
        None
    ] * (minimum_history - 1)

    assert signals[minimum_history - 1:] == [
        True
    ] * (n - minimum_history + 1)

    assert atr_values[minimum_history - 1:] == [
        2.0
    ] * (n - minimum_history + 1)


def test_historical_signals_reject_mismatched_lengths():
    with pytest.raises(ValueError, match="lengths"):
        generate_historical_signals(
            ticker="MSFT",
            highs=[110.0, 110.0],
            lows=[90.0],
            closes=[100.0, 100.0],
            volumes=[1000.0, 1000.0],
            strategy="mean_reversion",
        )


def test_historical_signals_reject_unknown_strategy():
    with pytest.raises(ValueError, match="Unknown strategy"):
        generate_historical_signals(
            ticker="MSFT",
            highs=[110.0],
            lows=[90.0],
            closes=[100.0],
            volumes=[1000.0],
            strategy="unknown",
        )

def test_real_mean_reversion_pipeline():
    n = 60

    signals, atr_values = generate_historical_signals(
        ticker="MSFT",
        highs=[105.0] * n,
        lows=[95.0] * n,
        closes=[100.0] * n,
        volumes=[1000.0] * n,
        strategy="mean_reversion",
    )

    assert len(signals) == n
    assert len(atr_values) == n

    assert signals[:50] == [False] * 50
    assert atr_values[:50] == [None] * 50

    assert all(
        value is not None and value > 0
        for value in atr_values[50:]
    )


def test_real_trend_breakout_pipeline():
    n = 30

    signals, atr_values = generate_historical_signals(
        ticker="MSFT",
        highs=[105.0] * n,
        lows=[95.0] * n,
        closes=[100.0] * n,
        volumes=[1000.0] * n,
        strategy="trend_breakout",
    )

    assert len(signals) == n
    assert len(atr_values) == n

    assert signals[:20] == [False] * 20
    assert atr_values[:20] == [None] * 20

    assert all(
        value is not None and value > 0
        for value in atr_values[20:]
    )

def test_donchian_excludes_current_session():
    # Previous 20 highs are all 100.
    # Current high is 200 and must be excluded.
    highs = [100.0] * 20 + [200.0]

    result = donchian_high(highs, period=20)

    assert result == pytest.approx(100.0)


def test_average_volume_excludes_current_session():
    # Previous 20 sessions have volume 1000.
    # Current volume is 10000 and must be excluded.
    volumes = [1000.0] * 20 + [10000.0]

    result = previous_average_volume(volumes, period=20)

    assert result == pytest.approx(1000.0)

def test_mean_reversion_exit_above_sma():
    closes = [100.0] * 49 + [110.0]

    exits = generate_mean_reversion_exits(closes)

    assert exits[:49] == [False] * 49
    assert exits[49] is True


def test_mean_reversion_no_exit_below_sma():
    closes = [100.0] * 49 + [90.0]

    exits = generate_mean_reversion_exits(closes)

    assert exits == [False] * 50


def test_mean_reversion_exit_requires_50_sessions():
    closes = [100.0] * 49

    exits = generate_mean_reversion_exits(closes)

    assert exits == [False] * 49


def test_mean_reversion_exit_on_equal_sma():
    closes = [100.0] * 50

    exits = generate_mean_reversion_exits(closes)

    assert exits[49] is True
