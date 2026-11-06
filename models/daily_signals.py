"""Frozen contracts for completed-session USD research decisions."""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from tools.historical_snapshot import Candle, EnvironmentRecord, FrozenModel, HistoricalSnapshot, TickerSnapshot, input_hash
from tools.market_regimes import MarketRegime


DAILY_UNIVERSE = ('AAPL', 'JNJ', 'JPM', 'MSFT', 'WMT', 'XOM')


class Session(FrozenModel):
    date: date
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @field_validator('date', mode='before')
    @classmethod
    def plain_date(cls, value):
        return Candle.session_date(value)

    @field_validator('opens_at', 'closes_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def valid_session(self):
        if not self.opens_at < self.closes_at:
            raise ValueError('Session open must precede close')
        if self.opens_at.date() != self.date or self.closes_at.date() != self.date:
            raise ValueError('US session label must match UTC open/close dates')
        return self


class SessionSchedule(FrozenModel):
    schema_version: Literal[1]
    calendar: Literal['US_EQUITIES']
    source: str = Field(min_length=1)
    available_at: AwareDatetime
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    sessions: tuple[Session, ...] = Field(min_length=1)

    @field_validator('available_at', 'coverage_start', 'coverage_end')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def valid_coverage(self):
        if not self.source.strip() or not self.coverage_start < self.coverage_end:
            raise ValueError('Schedule source and valid coverage required')
        for session in self.sessions:
            if not self.coverage_start <= session.opens_at < session.closes_at < self.coverage_end:
                raise ValueError('Session outside schedule coverage')
        if any(a.date >= b.date or a.closes_at >= b.opens_at for a, b in zip(self.sessions, self.sessions[1:])):
            raise ValueError('Schedule dates must be unique and ordered')
        return self

    def completed_sessions(self, decision_at: datetime) -> tuple[Session, ...]:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError('Timezone-aware decision timestamp required')
        if not self.coverage_start <= decision_at < self.coverage_end:
            raise ValueError('Schedule does not cover decision time')
        if self.available_at > decision_at:
            raise ValueError('Schedule was not available at decision time')
        return tuple(s for s in self.sessions if s.closes_at <= decision_at)


class BarAvailability(FrozenModel):
    date: date
    available_at: AwareDatetime
    final: StrictBool

    @field_validator('date', mode='before')
    @classmethod
    def plain_date(cls, value):
        return Candle.session_date(value)

    @field_validator('available_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)


class ObservedTicker(FrozenModel):
    snapshot: TickerSnapshot
    finality_source: str = Field(min_length=1)
    fetched_at: AwareDatetime
    availability: tuple[BarAvailability, ...]

    @field_validator('fetched_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)


class DailyStrategyConfiguration(FrozenModel):
    strategy: Literal['mean_reversion'] = 'mean_reversion'
    sma_period: Literal[50] = 50
    discount_fraction: Literal[0.95] = 0.95
    rsi_period: Literal[14] = 14
    rsi_recovery_threshold: Literal[30] = 30
    atr_period: Literal[14] = 14
    exit_rule: Literal['close_greater_than_or_equal_sma50'] = 'close_greater_than_or_equal_sma50'
    regime_sma_periods: tuple[Literal[50], Literal[200]] = (50, 200)
    regime_atr_threshold: Literal[0.05] = 0.05
    filtered_excluded_regimes: tuple[Literal['bear']] = ('bear',)
    variants: tuple[Literal['baseline'], Literal['bear_filtered']] = ('baseline', 'bear_filtered')
    minimum_completed_sessions: Literal[200] = 200
    conflict_priority: Literal['SELL_before_BUY'] = 'SELL_before_BUY'
    broker_currency: Literal['EUR'] = 'EUR'
    price_currency: Literal['USD'] = 'USD'
    order_submission_allowed: Literal[False] = False


class DailySignalInputs(FrozenModel):
    schema_version: Literal[1]
    schedule: SessionSchedule
    schedule_sha256: str
    snapshot: HistoricalSnapshot
    snapshot_sha256: str
    observed: tuple[ObservedTicker, ...]
    configuration: DailyStrategyConfiguration
    decision_at: AwareDatetime
    environment: EnvironmentRecord

    @field_validator('decision_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def validate_completed_inputs(self):
        if input_hash(self.schedule) != self.schedule_sha256 or input_hash(self.snapshot) != self.snapshot_sha256:
            raise ValueError('Schedule or snapshot hash mismatch')
        completed = self.schedule.completed_sessions(self.decision_at)
        if len(completed) < self.configuration.minimum_completed_sessions:
            raise ValueError('At least 200 completed sessions required for both variants')
        expected_dates = tuple(s.date for s in completed)
        if tuple(t.ticker for t in self.snapshot.tickers) != DAILY_UNIVERSE:
            raise ValueError('Exactly the six-stock universe is required')
        if len(self.observed) != 6 or {o.snapshot.ticker for o in self.observed} != set(DAILY_UNIVERSE):
            raise ValueError('Exactly one observation record per ticker required')
        snapshots = {t.ticker: t for t in self.snapshot.tickers}
        for observed in self.observed:
            ticker = observed.snapshot
            if not observed.finality_source.strip():
                raise ValueError('Named candle-finality source required')
            if ticker != snapshots[ticker.ticker]:
                raise ValueError('Observation and frozen snapshot differ')
            if ticker.currency != 'USD' or ticker.calendar != self.schedule.calendar:
                raise ValueError('USD prices and matching US schedule required; FX is unsupported')
            if ticker.price_adjustment != 'split_adjusted' or ticker.volume_adjustment != 'split_adjusted':
                raise ValueError('Daily V1 signals require declared split-adjusted price/volume inputs')
            dates = tuple(b.date for b in ticker.bars)
            if dates != expected_dates:
                raise ValueError('Missing, stale or unexpected sessions relative to frozen schedule')
            if tuple(a.date for a in observed.availability) != dates:
                raise ValueError('Availability dates must match every candle exactly')
            if observed.fetched_at > self.decision_at:
                raise ValueError('Data fetched after decision timestamp')
            for session, availability in zip(completed, observed.availability):
                if not availability.final:
                    raise ValueError('Incomplete candle: provider has not attested finality')
                if not session.closes_at <= availability.available_at <= observed.fetched_at <= self.decision_at:
                    raise ValueError('Candle availability violates session/decision causality')
        object.__setattr__(self, 'observed', tuple(sorted(self.observed, key=lambda o: o.snapshot.ticker)))
        return self


class DailyDecision(FrozenModel):
    ticker: str
    variant: Literal['baseline', 'bear_filtered']
    decision: Literal['BUY', 'SELL', 'HOLD']
    signal_date: date
    decision_at: AwareDatetime
    entry_signal: StrictBool
    exit_signal: StrictBool
    atr: float
    regime: MarketRegime
    price_currency: Literal['USD'] = 'USD'
    order_submission_allowed: Literal[False] = False


class DailySignalReport(FrozenModel):
    schema_version: Literal[1]
    inputs_sha256: str
    snapshot_sha256: str
    schedule_sha256: str
    configuration_sha256: str
    configuration: DailyStrategyConfiguration
    signal_date: date
    decision_at: AwareDatetime
    decisions: tuple[DailyDecision, ...]
    disclosures: tuple[str, ...]
