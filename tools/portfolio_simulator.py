"""Offline, synchronized long-only portfolio accounting."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite

from tools.backtesting import BacktestTrade, calculate_trade_result
from tools.risk_manager import calculate_risk_plan
from tools.performance_metrics import (
    calculate_total_return,
    calculate_annualized_return,
    calculate_annualized_volatility,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
)
from tools.trade_metrics import calculate_trade_expectancy, calculate_trade_expectancy_pct


@dataclass(frozen=True)
class PortfolioSeries:
    dates: Sequence[date]
    opens: Sequence[float]
    closes: Sequence[float]
    entry_signals: Sequence[bool]
    exit_signals: Sequence[bool]
    atr_values: Sequence[float | None] | None = None
    lows: Sequence[float] | None = None


@dataclass(frozen=True)
class PortfolioPosition:
    ticker: str
    quantity: int
    entry_price: float
    entry_day: int
    stop_price: float | None = None


@dataclass(frozen=True)
class PortfolioTrade:
    ticker: str
    trade: BacktestTrade


@dataclass(frozen=True)
class PortfolioSimulationResult:
    """Portfolio metrics use 252 sessions/year and zero risk-free rate.

    Trade expectancy is in the input capital currency (EUR for euro inputs).
    Percentage expectancy is an unweighted closed-trade mean, not portfolio
    return. Defaults retain compatibility with prior result construction.
    """
    dates: tuple[date, ...]
    final_cash: float
    positions: tuple[PortfolioPosition, ...]
    trades: tuple[PortfolioTrade, ...]
    equity_curve: tuple[float, ...]
    final_equity: float
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    annualized_volatility_pct: float = 0.0
    sharpe_ratio: float | None = None
    max_drawdown_pct: float = 0.0
    completed_trade_count: int = 0
    trade_expectancy: float | None = None
    trade_expectancy_pct: float | None = None


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def simulate_portfolio(
    series: Mapping[str, PortfolioSeries],
    initial_cash: float = 10_000.0,
    max_position_fraction: float = 0.20,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.001,
    risk_fraction: float = 0.01,
    atr_multiplier: float = 1.5,
) -> PortfolioSimulationResult:
    """Execute previous-session signals at the next open using shared cash.

    Inputs must have identical, strictly increasing daily dates. Index zero is
    the initial cash observation; its signals first execute at index one.
    After opening exits, each alphabetical entry is capped by current opening
    equity times max_position_fraction and available cash, including entry
    costs. Equity is recomputed after each fill. Existing positions are never
    topped up or rebalanced. A ticker exiting cannot re-enter that session.
    Closing equity marks open positions without hypothetical exit costs.
    Optional ATR uses the previous session's value and opening portfolio
    equity for sizing. Stops are fixed at slipped entry minus ATR distance.
    Gap stops execute at the open; intraday stops require lows and execute
    after all opening entries, including on entry day. Without lows, only
    opening gap stops are evaluated. No aggregate portfolio risk cap applies.
    """
    if not series:
        raise ValueError("At least one ticker required")
    if any(not isinstance(t, str) or not t.strip() for t in series):
        raise ValueError("Tickers must be nonempty strings")
    if not _finite_number(initial_cash) or initial_cash <= 0:
        raise ValueError("Initial cash must be finite and positive")
    if not _finite_number(max_position_fraction) or not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid maximum position fraction")
    if any(not _finite_number(r) or not 0 <= r < 1 for r in (fee_rate, slippage_rate)):
        raise ValueError("Invalid execution cost rates")
    if not _finite_number(risk_fraction) or not 0 < risk_fraction <= 1:
        raise ValueError("Invalid risk fraction")
    if not _finite_number(atr_multiplier) or atr_multiplier <= 0:
        raise ValueError("Invalid ATR multiplier")

    tickers = sorted(series)
    dates = tuple(series[tickers[0]].dates)
    n = len(dates)
    if n < 2:
        raise ValueError("At least two sessions required")
    if any(type(d) is not date for d in dates):
        raise ValueError("Sessions must be daily dates")
    if any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError("Dates must be unique and increasing")
    for data in series.values():
        if tuple(data.dates) != dates:
            raise ValueError("Ticker dates must be synchronized")
        if any(len(values) != n for values in (
            data.opens, data.closes, data.entry_signals, data.exit_signals,
        )):
            raise ValueError("Input lengths must match dates")
        if any(not _finite_number(p) or p <= 0 for p in (*data.opens, *data.closes)):
            raise ValueError("Prices must be finite and positive")
        if any(type(s) is not bool for s in (*data.entry_signals, *data.exit_signals)):
            raise ValueError("Signals must be boolean")
        if data.atr_values is not None:
            if len(data.atr_values) != n:
                raise ValueError("ATR length must match dates")
            if any(atr is not None and (not _finite_number(atr) or atr <= 0)
                   for atr in data.atr_values):
                raise ValueError("ATR values must be finite and positive when provided")
            if any(data.entry_signals[day] and data.atr_values[day] is None
                   for day in range(n - 1)):
                raise ValueError("Entry signal requires a valid ATR value")
        if data.lows is not None:
            if len(data.lows) != n:
                raise ValueError("Low prices must match dates")
            if any(not _finite_number(low) or low <= 0 for low in data.lows):
                raise ValueError("Low prices must be finite and positive")
            if any(low > opening or low > close for low, opening, close
                   in zip(data.lows, data.opens, data.closes)):
                raise ValueError("Low cannot exceed open or close")

    cash = initial_cash
    positions: dict[str, PortfolioPosition] = {}
    trades = []
    equity_curve = [initial_cash]

    def close_position(ticker: str, price: float, day: int, reason: str) -> None:
        nonlocal cash
        position = positions.pop(ticker)
        trade = calculate_trade_result(
            entry_price=position.entry_price,
            exit_price=price,
            quantity=position.quantity,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            exit_reason=reason,
            entry_day=position.entry_day,
            exit_day=day,
        )
        cash += price * (1 - slippage_rate) * position.quantity * (1 - fee_rate)
        trades.append(PortfolioTrade(ticker, trade))

    for day in range(1, n):
        exited = set()
        for ticker in tickers:
            data = series[ticker]
            position = positions.get(ticker)
            gap_stop = (position is not None and position.stop_price is not None
                        and data.opens[day] <= position.stop_price)
            if position is not None and (data.exit_signals[day - 1] or gap_stop):
                close_position(ticker, data.opens[day], day,
                               "stop_gap" if gap_stop else "signal")
                exited.add(ticker)

        for ticker in tickers:
            data = series[ticker]
            if ticker in positions or ticker in exited or not data.entry_signals[day - 1]:
                continue
            opening_equity = cash + sum(
                p.quantity * series[t].opens[day] for t, p in positions.items()
            )
            cost_per_share = data.opens[day] * (1 + slippage_rate) * (1 + fee_rate)
            budget = min(cash, opening_equity * max_position_fraction)
            quantity = int(budget // cost_per_share)
            stop_price = None
            if data.atr_values is not None:
                plan = calculate_risk_plan(
                    capital=opening_equity,
                    entry_price=data.opens[day] * (1 + slippage_rate),
                    atr=data.atr_values[day - 1],
                    risk_fraction=risk_fraction,
                    max_position_fraction=max_position_fraction,
                    atr_multiplier=atr_multiplier,
                )
                quantity = min(quantity, plan.quantity)
                stop_price = plan.stop_price
            if quantity > 0:
                cash -= quantity * cost_per_share
                positions[ticker] = PortfolioPosition(
                    ticker, quantity, data.opens[day], day, stop_price,
                )

        # Intraday proceeds cannot finance any opening entry in this session.
        for ticker in tickers:
            data = series[ticker]
            position = positions.get(ticker)
            if (position is not None and position.stop_price is not None
                    and data.lows is not None and data.lows[day] <= position.stop_price):
                close_position(ticker, position.stop_price, day, "stop_intraday")

        equity_curve.append(cash + sum(
            p.quantity * series[t].closes[day] for t, p in positions.items()
        ))

    completed_trades = tuple(record.trade for record in trades)
    return PortfolioSimulationResult(
        dates=dates,
        final_cash=cash,
        positions=tuple(positions[t] for t in sorted(positions)),
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        final_equity=equity_curve[-1],
        total_return_pct=calculate_total_return(equity_curve),
        annualized_return_pct=calculate_annualized_return(equity_curve),
        annualized_volatility_pct=(
            calculate_annualized_volatility(equity_curve) if n >= 3 else 0.0
        ),
        sharpe_ratio=calculate_sharpe_ratio(equity_curve) if n >= 3 else None,
        max_drawdown_pct=calculate_max_drawdown(equity_curve),
        completed_trade_count=len(completed_trades),
        trade_expectancy=calculate_trade_expectancy(completed_trades),
        trade_expectancy_pct=calculate_trade_expectancy_pct(completed_trades),
    )
