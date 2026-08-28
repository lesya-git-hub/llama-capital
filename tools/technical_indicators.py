def calculate_ema(
    values: list[float],
    period: int,
) -> float:
    if len(values) < period:
        raise ValueError(
            f"At least {period} values are required "
            f"to calculate EMA{period}."
        )

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = (
            value * multiplier
            + ema * (1 - multiplier)
        )

    return ema


def is_above_ema(
    current_price: float,
    values: list[float],
    period: int,
) -> bool:
    ema = calculate_ema(
        values,
        period,
    )

    return current_price > ema