
from __future__ import annotations

from collections.abc import Sequence

from tools.backtesting import BacktestTrade


def calculate_trade_expectancy(
    trades: Sequence[BacktestTrade],
) -> float | None:
    """Return average realized net P&L per closed trade.

    Returns None when no completed trades exist.
    """
    if not trades:
        return None

    return sum(trade.net_pnl for trade in trades) / len(trades)


def calculate_trade_expectancy_pct(
    trades: Sequence[BacktestTrade],
) -> float | None:
    """Return arithmetic mean of completed trade returns in percent.

    This is an unweighted per-trade average, not portfolio return.
    """
    if not trades:
        return None

    return sum(trade.return_pct for trade in trades) / len(trades)
