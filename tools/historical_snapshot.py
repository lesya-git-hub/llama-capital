"""Versioned offline inputs and single-stock experiment replay.

No downloads, adjustment inference, dividend payments or split share changes.
"""

from datetime import date
from hashlib import sha256
from importlib.metadata import version
import inspect
import json
from pathlib import Path
import platform
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from tools.historical_simulator import SimulationResult, simulate_long_only


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Candle(FrozenModel):
    date: date
    open: float = Field(gt=0, strict=True)
    high: float = Field(gt=0, strict=True)
    low: float = Field(gt=0, strict=True)
    close: float = Field(gt=0, strict=True)
    volume: float = Field(ge=0, strict=True)
    # Dividend per share in the declared currency and price share basis.
    dividend: float = Field(ge=0, strict=True)
    # New shares / old shares; 1 means no split. Date is the effective session.
    split_ratio: float = Field(gt=0, strict=True)

    @field_validator("date", mode="before")
    @classmethod
    def session_date(cls, value):
        if type(value) is date:
            return value
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        raise ValueError("Session date must be YYYY-MM-DD or a plain date")

    @model_validator(mode="after")
    def valid_candle(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Invalid OHLC relationships")
        return self


class TickerSnapshot(FrozenModel):
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.^=-]*$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source: str = Field(min_length=1)
    # Named exchange/session convention supplied by the snapshot author.
    calendar: str = Field(min_length=1)
    price_adjustment: Literal["unadjusted", "split_adjusted", "dividend_adjusted"]
    volume_adjustment: Literal["unadjusted", "split_adjusted"]
    dividend_convention: Literal["recorded_not_applied"]
    split_convention: Literal["events_recorded_prices_unadjusted", "events_recorded_prices_adjusted"]
    bars: tuple[Candle, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def valid_dates_and_basis(self):
        dates = tuple(bar.date for bar in self.bars)
        if any(a >= b for a, b in zip(dates, dates[1:])):
            raise ValueError("Dates must be unique and increasing")
        raw = self.price_adjustment == "unadjusted"
        if raw != (self.split_convention == "events_recorded_prices_unadjusted"):
            raise ValueError("Inconsistent split convention and price adjustment")
        if not self.source.strip() or not self.calendar.strip():
            raise ValueError("Source and calendar must not be blank")
        return self


class HistoricalSnapshot(FrozenModel):
    schema_version: Literal[1]
    tickers: tuple[TickerSnapshot, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def synchronized(self):
        if len({item.ticker for item in self.tickers}) != len(self.tickers):
            raise ValueError("Duplicate ticker identity")
        first = self.tickers[0]
        dates = tuple(bar.date for bar in first.bars)
        for item in self.tickers[1:]:
            if item.calendar != first.calendar or tuple(bar.date for bar in item.bars) != dates:
                raise ValueError("Inconsistent ticker calendars")
        # Ticker ordering has no economic meaning in a data snapshot.
        object.__setattr__(self, "tickers", tuple(sorted(self.tickers, key=lambda item: item.ticker)))
        return self


def canonical_json(value: FrozenModel) -> str:
    """UTF-8 JSON, sorted object keys, no whitespace/NaN, normalized numbers."""
    return json.dumps(value.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def input_hash(value: FrozenModel) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)


def load_snapshot(path: str | Path) -> HistoricalSnapshot:
    return HistoricalSnapshot.model_validate(_read_json(path))


class ExecutionParameters(FrozenModel):
    initial_cash: float = Field(gt=0, strict=True)
    max_position_fraction: float = Field(gt=0, le=1, strict=True)
    risk_fraction: float = Field(gt=0, le=1, strict=True)
    atr_multiplier: float = Field(gt=0, strict=True)
    fee_rate: float = Field(ge=0, lt=1, strict=True)
    slippage_rate: float = Field(ge=0, lt=1, strict=True)


class EnvironmentRecord(FrozenModel):
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    working_tree_dirty: StrictBool
    execution_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    python_version: str
    # Sorted immutable pairs, not mutable dictionaries.
    dependency_versions: tuple[tuple[str, str], ...]


def capture_environment() -> EnvironmentRecord:
    root = Path(__file__).resolve().parents[1]

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    sources = ("tools/historical_snapshot.py", "tools/historical_simulator.py",
               "tools/risk_manager.py", "tools/backtesting.py",
               "tools/performance_metrics.py", "tools/trade_metrics.py")
    digest = sha256()
    for name in sources:
        digest.update(name.encode("utf-8") + b"\0" + (root / name).read_bytes() + b"\0")
    return EnvironmentRecord(
        code_commit=git("rev-parse", "HEAD"),
        working_tree_dirty=bool(git("status", "--porcelain")),
        execution_source_sha256=digest.hexdigest(),
        python_version=platform.python_version(),
        dependency_versions=tuple((name, version(name)) for name in ("pandas", "pydantic", "yfinance")),
    )


class HistoricalExperiment(FrozenModel):
    schema_version: Literal[1]
    snapshot: HistoricalSnapshot
    snapshot_sha256: str
    ticker: str
    # Caller identifies the frozen signal artifact; generation is outside 20B.
    signal_description: str = Field(min_length=1)
    entry_signals: tuple[StrictBool, ...]
    exit_signals: tuple[StrictBool, ...]
    atr_values: tuple[float | None, ...] | None
    parameters: ExecutionParameters
    environment: EnvironmentRecord
    return_basis: Literal["price_return_excluding_dividends"]

    @model_validator(mode="after")
    def valid_inputs(self):
        if input_hash(self.snapshot) != self.snapshot_sha256:
            raise ValueError("Snapshot hash mismatch")
        item = self.selected_ticker()
        n = len(item.bars)
        if len(self.entry_signals) != n or len(self.exit_signals) != n:
            raise ValueError("Signal lengths must match snapshot")
        if self.atr_values is not None:
            if len(self.atr_values) != n:
                raise ValueError("ATR length must match snapshot")
            if any(atr is not None and atr <= 0 for atr in self.atr_values):
                raise ValueError("ATR must be positive")
            if any(entry and atr is None for entry, atr in zip(self.entry_signals[:-1], self.atr_values[:-1])):
                raise ValueError("Executable entries require ATR")
        if item.price_adjustment == "dividend_adjusted":
            raise ValueError("Dividend-adjusted prices cannot be reported as price return")
        if item.price_adjustment == "unadjusted" and any(b.split_ratio != 1 for b in item.bars):
            raise ValueError("Unadjusted split events require unsupported share accounting")
        return self

    def selected_ticker(self) -> TickerSnapshot:
        for item in self.snapshot.tickers:
            if item.ticker == self.ticker:
                return item
        raise ValueError("Experiment ticker not found in snapshot")


def freeze_experiment(snapshot: HistoricalSnapshot, ticker: str, entry_signals,
                      exit_signals, *, signal_description: str, atr_values=None,
                      **parameters) -> HistoricalExperiment:
    """Resolve simulator defaults now, so later default changes cannot alter replay."""
    names = ExecutionParameters.model_fields
    if parameters.keys() - names.keys():
        raise ValueError("Unknown execution parameter")
    defaults = inspect.signature(simulate_long_only).parameters
    effective = {name: parameters.get(name, defaults[name].default) for name in names}
    return HistoricalExperiment(
        schema_version=1, snapshot=snapshot, snapshot_sha256=input_hash(snapshot),
        ticker=ticker, signal_description=signal_description,
        entry_signals=entry_signals, exit_signals=exit_signals, atr_values=atr_values,
        parameters=ExecutionParameters(**effective), environment=capture_environment(),
        return_basis="price_return_excluding_dividends",
    )


def load_experiment(path: str | Path, *, expected_sha256: str) -> HistoricalExperiment:
    experiment = HistoricalExperiment.model_validate(_read_json(path))
    if input_hash(experiment) != expected_sha256:
        raise ValueError("Experiment hash mismatch")
    return experiment


def replay_experiment(experiment: HistoricalExperiment) -> SimulationResult:
    """Fail closed on changed execution source/runtime versions; never fetch data."""
    current = capture_environment()
    for field in ("code_commit", "execution_source_sha256", "python_version", "dependency_versions"):
        if getattr(current, field) != getattr(experiment.environment, field):
            raise ValueError(f"Replay environment mismatch: {field}")
    bars = experiment.selected_ticker().bars
    return simulate_long_only(
        opens=tuple(bar.open for bar in bars), closes=tuple(bar.close for bar in bars),
        lows=tuple(bar.low for bar in bars), entry_signals=experiment.entry_signals,
        exit_signals=experiment.exit_signals, atr_values=experiment.atr_values,
        **experiment.parameters.model_dump(),
    )
