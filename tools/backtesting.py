
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from collections.abc import Sequence


@dataclass(frozen=True)
class BacktestTrade:
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    costs: float
    net_pnl: float
    return_pct: float
    exit_reason: str = "unknown"
    entry_day: int | None = None
    exit_day: int | None = None


def calculate_trade_result(
    entry_price: float,
    exit_price: float,
    quantity: int,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.001,
    exit_reason: str = "unknown",
    entry_day: int | None = None,
    exit_day: int | None = None,
) -> BacktestTrade:
    """Calculate net P&L for a long trade with execution costs."""

    values = (
        entry_price,
        exit_price,
        fee_rate,
        slippage_rate,
    )

    if any(not isfinite(v) for v in values):
        raise ValueError("All inputs must be finite")

    if entry_price <= 0 or exit_price <= 0:
        raise ValueError("Prices must be positive")

    if quantity <= 0 or isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("Quantity must be a positive integer")

    if not 0 <= fee_rate < 1:
        raise ValueError("Invalid fee rate")

    if not 0 <= slippage_rate < 1:
        raise ValueError("Invalid slippage rate")

    effective_entry = entry_price * (1 + slippage_rate)
    effective_exit = exit_price * (1 - slippage_rate)

    entry_value = effective_entry * quantity
    exit_value = effective_exit * quantity

    entry_fee = entry_value * fee_rate
    exit_fee = exit_value * fee_rate

    gross_pnl = (exit_price - entry_price) * quantity
    costs = (
        (effective_entry - entry_price) * quantity
        + (exit_price - effective_exit) * quantity
        + entry_fee
        + exit_fee
    )

    net_pnl = gross_pnl - costs
    invested_capital = entry_value + entry_fee

    return BacktestTrade(
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        gross_pnl=gross_pnl,
        exit_reason=exit_reason,
        costs=costs,
        net_pnl=net_pnl,
        return_pct=(net_pnl / invested_capital) * 100,
        entry_day=entry_day,
        exit_day=exit_day,
    )


def calculate_win_rate(
    trades: Sequence[BacktestTrade],
) -> float:
    """Percentage of trades with positive net P&L."""

    if not trades:
        return 0.0

    wins = sum(trade.net_pnl > 0 for trade in trades)

    return 100.0 * wins / len(trades)
