
from __future__ import annotations
from tools.risk_manager import calculate_risk_plan
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from tools.performance_metrics import (
    calculate_max_drawdown,
    calculate_total_return,
    calculate_annualized_return,
    calculate_annualized_volatility,
    calculate_sharpe_ratio,
)

from tools.trade_metrics import (
    calculate_trade_expectancy,
    calculate_trade_expectancy_pct,
)

from tools.backtesting import BacktestTrade, calculate_trade_result


@dataclass(frozen=True)
class SimulationResult:
    trades: tuple[BacktestTrade, ...]
    final_cash: float
    equity_curve: tuple[float, ...]
    open_quantity: int
    final_equity: float
    max_drawdown_pct: float
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float | None = None 
    exposure_pct: float = 0.0
    trade_expectancy: float | None = None
    trade_expectancy_pct: float | None = None

def simulate_long_only(
    opens: Sequence[float],
    entry_signals: Sequence[bool],
    exit_signals: Sequence[bool],
    initial_cash: float = 10_000.0,
    max_position_fraction: float = 0.20,
    atr_values: Sequence[float | None] | None = None,
    risk_fraction: float = 0.01,
    atr_multiplier: float = 1.5,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.001,
    lows: Sequence[float] | None = None,
    closes: Sequence[float] | None = None,
) -> SimulationResult:
    """Execute close-generated signals at the next session's open.

    One position at a time; full exits; whole shares only.
    Signals at index t execute at the open of t+1.
    """
    n = len(opens)
    
    if atr_values is not None:
        if len(atr_values) != n:
            raise ValueError("ATR length must match prices")

        if any(
            atr is not None
            and (not isfinite(atr) or atr <= 0)
            for atr in atr_values
        ):
            raise ValueError(
                "ATR values must be finite and positive when provided"
            )

        if any(
            entry_signals[day] and atr_values[day] is None
            for day in range(n - 1)
        ):
            raise ValueError(
                "Entry signal requires a valid ATR value"
            )


    if not isfinite(risk_fraction) or not 0 < risk_fraction <= 1:
        raise ValueError("Invalid risk fraction")

    if not isfinite(atr_multiplier) or atr_multiplier <= 0:
        raise ValueError("Invalid ATR multiplier")

    if (
        not isfinite(max_position_fraction)
        or not 0 < max_position_fraction <= 1
    ):
        raise ValueError("Invalid maximum position fraction")

    if not (
        n == len(entry_signals) == len(exit_signals)
    ):
        raise ValueError("Input lengths must match")

    if n < 2:
        raise ValueError("At least two sessions required")

    if not isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("Initial cash must be finite and positive")

    if any(not isfinite(p) or p <= 0 for p in opens):
        raise ValueError("Open prices must be finite and positive")
    
    
    if lows is not None:
        if len(lows) != n:
            raise ValueError("Low prices must match open prices")

        if any(
            not isfinite(low) or low <= 0
            for low in lows
        ):
            raise ValueError("Low prices must be finite and positive")

        if any(low > opening for low, opening in zip(lows, opens)):
            raise ValueError("Session low cannot exceed opening price")
    if closes is not None:
        if len(closes) != n:
            raise ValueError("Closing prices must match open prices")

        if any(
            not isfinite(price) or price <= 0
            for price in closes
        ):
            raise ValueError(
                "Closing prices must be finite and positive"
            )

        if lows is not None and any(
            close < low for close, low in zip(closes, lows)
        ):
            raise ValueError(
                "Closing price cannot be below session low"
            )
    if not 0 <= fee_rate < 1 or not 0 <= slippage_rate < 1:
        raise ValueError("Invalid execution cost rates")

    if not all(type(s) is bool for s in entry_signals):
        raise ValueError("Entry signals must be boolean")

    if not all(type(s) is bool for s in exit_signals):
        raise ValueError("Exit signals must be boolean")

    cash = initial_cash
    quantity = 0
    entry_price = 0.0
    stop_price = None
    entry_day = None
    trades = []
    equity_curve = [initial_cash]
    invested_sessions = 0


    for day in range(1, n):
        signal_day = day - 1
        opening_price = opens[day]
        held_during_session = quantity > 0


        if quantity > 0 and (
            exit_signals[signal_day]
            or (stop_price is not None and opening_price <= stop_price)
        ):
            exit_reason = (
                "stop_gap"
                if stop_price is not None and opening_price <= stop_price
                else "signal"
            )
            trade = calculate_trade_result(
                entry_price=entry_price,
                exit_price=opening_price,
                quantity=quantity,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
                exit_reason=exit_reason,
                entry_day=entry_day,
                exit_day=day,
            )

            cash += (
                opening_price
                * (1 - slippage_rate)
                * quantity
                * (1 - fee_rate)
            )

            trades.append(trade)
            quantity = 0
            entry_price = 0.0
            stop_price = None
            entry_day = None

        elif quantity == 0 and entry_signals[signal_day]:
            effective_entry = opening_price * (1 + slippage_rate)
            cost_per_share = effective_entry * (1 + fee_rate)

            
            allocation = cash * max_position_fraction
            shares = int(allocation // cost_per_share)

            if atr_values is not None:
                plan = calculate_risk_plan(
                    capital=cash,
                    entry_price=effective_entry,
                    atr=atr_values[signal_day],
                    risk_fraction=risk_fraction,
                    max_position_fraction=max_position_fraction,
                    atr_multiplier=atr_multiplier,
                )

                shares = min(shares, plan.quantity)


            
            if shares > 0:
                cash -= shares * cost_per_share
                quantity = shares
                held_during_session = True
                entry_price = opening_price
                entry_day = day

                if atr_values is not None:
                    stop_price = (
                        opening_price * (1 + slippage_rate)
                        - atr_multiplier * atr_values[signal_day]
                    )
                else:
                    stop_price = None
            
        # Check intraday stop after the opening execution.
        # This also covers the session in which we entered.
        if (
            lows is not None
            and quantity > 0
            and stop_price is not None
            and lows[day] <= stop_price
        ):
            trade = calculate_trade_result(
                entry_price=entry_price,
                exit_price=stop_price,
                quantity=quantity,
                entry_day=entry_day,
                exit_day=day,
                exit_reason="stop_intraday",	
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
            )

            cash += (
                stop_price
                * (1 - slippage_rate)
                * quantity
                * (1 - fee_rate)
            )

            trades.append(trade)
            quantity = 0
            entry_price = 0.0
            stop_price = None
            entry_day = None
        
        if quantity > 0:
            held_during_session = True

        if held_during_session:
            invested_sessions += 1

        valuation_price = (
            closes[day] if closes is not None else opens[day]
        )

        equity_curve.append(
            cash + quantity * valuation_price
        )
    
    
    return SimulationResult(
        trades=tuple(trades),
        final_cash=cash,
        open_quantity=quantity,
        final_equity=equity_curve[-1],
        equity_curve=tuple(equity_curve),
        max_drawdown_pct=calculate_max_drawdown(equity_curve),
        total_return_pct=calculate_total_return(equity_curve),
        annualized_return_pct=calculate_annualized_return(
            equity_curve
        ),
        annualized_volatility_pct=(
            calculate_annualized_volatility(equity_curve)
            if len(equity_curve) >= 3
            else 0.0
        ),
        sharpe_ratio=(
            calculate_sharpe_ratio(equity_curve)
            if len(equity_curve) >= 3
            else None
        ),
        exposure_pct=invested_sessions / (n - 1) * 100,
        trade_expectancy=calculate_trade_expectancy(trades),
        trade_expectancy_pct=calculate_trade_expectancy_pct(trades),
    )





