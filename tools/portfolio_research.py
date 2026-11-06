"""Offline portfolio experiments and deterministic research reports."""

from datetime import date
from hashlib import sha256
import inspect
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from tools.backtesting import BacktestTrade
from tools.historical_snapshot import (
    EnvironmentRecord, ExecutionParameters, FrozenModel, HistoricalExperiment,
    HistoricalSnapshot, _read_json, capture_environment, input_hash,
)
from tools.portfolio_simulator import PortfolioSeries, simulate_portfolio


class FrozenSignals(FrozenModel):
    ticker: str
    signal_description: str = Field(min_length=1)
    entry_signals: tuple[StrictBool, ...]
    exit_signals: tuple[StrictBool, ...]
    atr_values: tuple[Annotated[float, Field(strict=True, gt=0)] | None, ...] | None


def capture_portfolio_environment() -> EnvironmentRecord:
    """Extend 20B provenance without changing its single-stock fingerprint."""
    base = capture_environment()
    root = Path(__file__).resolve().parents[1]
    digest = sha256(base.execution_source_sha256.encode("ascii"))
    for name in ("tools/portfolio_simulator.py", "tools/portfolio_research.py"):
        digest.update(name.encode("utf-8") + b"\0" + (root / name).read_bytes() + b"\0")
    return base.model_copy(update={"execution_source_sha256": digest.hexdigest()})


class PortfolioExperiment(FrozenModel):
    schema_version: Literal[1]
    experiment_type: Literal["offline_portfolio"]
    snapshot: HistoricalSnapshot
    snapshot_sha256: str
    currency: str
    signals: tuple[FrozenSignals, ...]
    parameters: ExecutionParameters
    environment: EnvironmentRecord
    return_basis: Literal["price_return_excluding_dividends"]
    entry_priority: Literal["alphabetical"]

    @model_validator(mode="after")
    def valid_inputs(self):
        if input_hash(self.snapshot) != self.snapshot_sha256:
            raise ValueError("Snapshot hash mismatch")
        tickers = {item.ticker for item in self.snapshot.tickers}
        if len(self.signals) != len(tickers) or {s.ticker for s in self.signals} != tickers:
            raise ValueError("Exactly one signal record required per snapshot ticker")
        if {item.currency for item in self.snapshot.tickers} != {self.currency}:
            raise ValueError("All tickers must match portfolio currency; FX is unsupported")
        for signals in self.signals:
            # Reuse 20B length, ATR, hash and corporate-action validation.
            HistoricalExperiment(
                schema_version=1, snapshot=self.snapshot, snapshot_sha256=self.snapshot_sha256,
                ticker=signals.ticker, signal_description=signals.signal_description,
                entry_signals=signals.entry_signals, exit_signals=signals.exit_signals,
                atr_values=signals.atr_values, parameters=self.parameters,
                environment=self.environment, return_basis=self.return_basis,
            )
        object.__setattr__(self, "signals", tuple(sorted(self.signals, key=lambda item: item.ticker)))
        return self


def freeze_portfolio_experiment(
    snapshot: HistoricalSnapshot, signals: tuple[FrozenSignals, ...], *, currency: str,
    **parameters,
) -> PortfolioExperiment:
    names = ExecutionParameters.model_fields
    if parameters.keys() - names.keys():
        raise ValueError("Unknown execution parameter")
    defaults = inspect.signature(simulate_portfolio).parameters
    effective = {name: parameters.get(name, defaults[name].default) for name in names}
    return PortfolioExperiment(
        schema_version=1, experiment_type="offline_portfolio", snapshot=snapshot,
        snapshot_sha256=input_hash(snapshot), signals=signals, currency=currency,
        parameters=ExecutionParameters(**effective), environment=capture_portfolio_environment(),
        return_basis="price_return_excluding_dividends", entry_priority="alphabetical",
    )


def load_portfolio_experiment(path: str | Path, *, expected_sha256: str) -> PortfolioExperiment:
    experiment = PortfolioExperiment.model_validate(_read_json(path))
    if input_hash(experiment) != expected_sha256:
        raise ValueError("Experiment hash mismatch")
    return experiment


class EquityObservation(FrozenModel):
    date: date
    equity: float


class ResearchTrade(FrozenModel):
    ticker: str
    entry_date: date
    exit_date: date
    accounting: BacktestTrade


class MarkedPosition(FrozenModel):
    ticker: str
    quantity: int
    entry_date: date
    entry_price: float
    stop_price: float | None
    closing_price: float
    entry_cost_basis: float
    marked_value: float
    unrealized_pnl: float


class PortfolioResearchReport(FrozenModel):
    schema_version: Literal[1]
    experiment_sha256: str
    snapshot_sha256: str
    signals_sha256: tuple[tuple[str, str], ...]
    currency: str
    return_basis: Literal["price_return_excluding_dividends"]
    environment: EnvironmentRecord
    parameters: ExecutionParameters
    entry_priority: Literal["alphabetical"]
    starting_capital: float
    ending_capital: float
    ending_cash: float
    marked_holdings_value: float
    realized_pnl: float
    unrealized_pnl: float
    incurred_execution_costs: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    annualized_volatility_pct: float
    completed_trade_count: int
    trade_expectancy: float | None
    trade_expectancy_pct: float | None
    equity_curve: tuple[EquityObservation, ...]
    completed_trades: tuple[ResearchTrade, ...]
    open_positions: tuple[MarkedPosition, ...]
    disclosures: tuple[str, ...]


DISCLOSURES = (
    "No aggregate portfolio risk or exposure cap; sizing budgets apply per entry.",
    "ATR stops are fixed at entry, not trailing; tickers without ATR have no stop.",
    "Dividends are excluded from performance; results are price return, not total return.",
    "Idealized fills: opening execution and stop-price fills with fixed fees/slippage; no liquidity or partial-fill model.",
    "Opening exits precede alphabetical entries; intraday stop proceeds cannot fund opening entries.",
    "Open positions are marked at closing prices without liquidation costs; unrealized P&L includes entry costs.",
    "Annualization assumes 252 sessions/year and zero risk-free rate; short-series volatility follows simulator conventions.",
    "Matching supplied calendars does not establish exchange-session completeness or vendor adjustment accuracy.",
)


def replay_portfolio_experiment(
    experiment: PortfolioExperiment, *, expected_sha256: str,
) -> PortfolioResearchReport:
    # Revalidate even caller-created model_copy/model_construct instances.
    experiment = PortfolioExperiment.model_validate(experiment.model_dump(mode="json"))
    if input_hash(experiment) != expected_sha256:
        raise ValueError("Experiment hash mismatch")
    current = capture_portfolio_environment()
    for field in ("code_commit", "execution_source_sha256", "python_version", "dependency_versions"):
        if getattr(current, field) != getattr(experiment.environment, field):
            raise ValueError(f"Replay environment mismatch: {field}")
    signals = {item.ticker: item for item in experiment.signals}
    series = {}
    closing_prices = {}
    for item in experiment.snapshot.tickers:
        frozen = signals[item.ticker]
        series[item.ticker] = PortfolioSeries(
            dates=tuple(bar.date for bar in item.bars),
            opens=tuple(bar.open for bar in item.bars),
            closes=tuple(bar.close for bar in item.bars),
            lows=tuple(bar.low for bar in item.bars),
            entry_signals=frozen.entry_signals, exit_signals=frozen.exit_signals,
            atr_values=frozen.atr_values,
        )
        closing_prices[item.ticker] = item.bars[-1].close
    result = simulate_portfolio(series, **experiment.parameters.model_dump())
    params = experiment.parameters
    positions = tuple(MarkedPosition(
        ticker=p.ticker, quantity=p.quantity, entry_date=result.dates[p.entry_day],
        entry_price=p.entry_price, stop_price=p.stop_price,
        closing_price=closing_prices[p.ticker],
        entry_cost_basis=p.quantity * p.entry_price * (1 + params.slippage_rate) * (1 + params.fee_rate),
        marked_value=p.quantity * closing_prices[p.ticker],
        unrealized_pnl=p.quantity * closing_prices[p.ticker]
        - p.quantity * p.entry_price * (1 + params.slippage_rate) * (1 + params.fee_rate),
    ) for p in result.positions)
    return PortfolioResearchReport(
        schema_version=1, experiment_sha256=expected_sha256,
        snapshot_sha256=experiment.snapshot_sha256,
        signals_sha256=tuple((s.ticker, input_hash(s)) for s in experiment.signals),
        currency=experiment.currency, return_basis=experiment.return_basis,
        environment=experiment.environment, parameters=params, entry_priority=experiment.entry_priority,
        starting_capital=params.initial_cash, ending_capital=result.final_equity,
        ending_cash=result.final_cash, marked_holdings_value=sum(p.marked_value for p in positions),
        realized_pnl=sum(t.trade.net_pnl for t in result.trades),
        unrealized_pnl=sum(p.unrealized_pnl for p in positions),
        incurred_execution_costs=sum(t.trade.costs for t in result.trades) + sum(
            p.entry_cost_basis - p.quantity * p.entry_price for p in positions
        ),
        total_return_pct=result.total_return_pct, annualized_return_pct=result.annualized_return_pct,
        max_drawdown_pct=result.max_drawdown_pct, sharpe_ratio=result.sharpe_ratio,
        annualized_volatility_pct=result.annualized_volatility_pct,
        completed_trade_count=result.completed_trade_count, trade_expectancy=result.trade_expectancy,
        trade_expectancy_pct=result.trade_expectancy_pct,
        equity_curve=tuple(EquityObservation(date=d, equity=e) for d, e in zip(result.dates, result.equity_curve)),
        completed_trades=tuple(ResearchTrade(
            ticker=t.ticker, entry_date=result.dates[t.trade.entry_day],
            exit_date=result.dates[t.trade.exit_day], accounting=t.trade,
        ) for t in result.trades),
        open_positions=positions, disclosures=DISCLOSURES,
    )
