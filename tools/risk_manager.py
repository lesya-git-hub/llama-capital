
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite


@dataclass(frozen=True)
class RiskPlan:
    entry_price: float
    stop_price: float
    quantity: int
    position_value: float
    capital_at_risk: float


def calculate_risk_plan(
    capital: float,
    entry_price: float,
    atr: float,
    risk_fraction: float = 0.01,
    max_position_fraction: float = 0.20,
    atr_multiplier: float = 1.5,
) -> RiskPlan:
    """Size a long position using ATR and capital limits."""

    values = (
        capital,
        entry_price,
        atr,
        risk_fraction,
        max_position_fraction,
        atr_multiplier,
    )

    if any(not isfinite(value) for value in values):
        raise ValueError("All inputs must be finite")

    if capital <= 0 or entry_price <= 0 or atr <= 0:
        raise ValueError("Capital, entry price and ATR must be positive")

    if not 0 < risk_fraction <= 1:
        raise ValueError("Invalid risk fraction")

    if not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid maximum position fraction")

    if atr_multiplier <= 0:
        raise ValueError("ATR multiplier must be positive")

    stop_distance = atr * atr_multiplier
    stop_price = entry_price - stop_distance

    if stop_price <= 0:
        raise ValueError("ATR stop must remain above zero")

    risk_budget = capital * risk_fraction
    position_budget = capital * max_position_fraction

    quantity_by_risk = floor(risk_budget / stop_distance)
    quantity_by_capital = floor(position_budget / entry_price)

    quantity = min(quantity_by_risk, quantity_by_capital)

    position_value = quantity * entry_price
    capital_at_risk = quantity * stop_distance

    return RiskPlan(
        entry_price=entry_price,
        stop_price=stop_price,
        quantity=quantity,
        position_value=position_value,
        capital_at_risk=capital_at_risk,
    )
