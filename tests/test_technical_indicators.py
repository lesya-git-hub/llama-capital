import pytest

from tools.technical_indicators import (
    calculate_ema,
    is_above_ema,
)


def test_calculate_ema() -> None:
    values = [
        float(value)
        for value in range(1, 11)
    ]

    ema = calculate_ema(
        values,
        period=5,
    )

    assert ema == pytest.approx(
        8.0,
    )


def test_calculate_ema_requires_enough_values() -> None:
    with pytest.raises(
        ValueError,
        match="At least 5 values",
    ):
        calculate_ema(
            [1.0, 2.0, 3.0],
            period=5,
        )


def test_is_above_ema() -> None:
    values = [
        float(value)
        for value in range(1, 11)
    ]

    assert is_above_ema(
        current_price=9.0,
        values=values,
        period=5,
    ) is True

    assert is_above_ema(
        current_price=7.0,
        values=values,
        period=5,
    ) is False