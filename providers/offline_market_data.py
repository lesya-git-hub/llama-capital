"""Synthetic-only source archive and replaceable adapter. No network transport."""

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from models.daily_signals import DAILY_UNIVERSE, BarAvailability, ObservedTicker, Session
from tools.historical_snapshot import FrozenModel, TickerSnapshot, canonical_json, input_hash
from tools.market_verification import CalendarArtifact, Exchange, ProviderEvidenceArtifact


class OfflineProviderError(RuntimeError):
    """An offline source failed; callers must reject the complete batch."""


class OfflineRateLimitError(OfflineProviderError):
    """Recorded/mock rate-limit failure; no implicit retries or network fallback."""


class SourceProvider(Protocol):
    def fetch_source(self, ticker: str, sessions: tuple[Session, ...]) -> 'SourceObservation': ...


class SourceObservation(FrozenModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test'] = 'synthetic_test'
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    exchange: Exchange
    source_timestamp: AwareDatetime | None  # None means unavailable, never inferred.
    retrieved_at: AwareDatetime
    raw_payload: str  # Exact UTF-8 fixture response, not reconstructed normalized JSON.
    raw_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    snapshot: TickerSnapshot

    @model_validator(mode='after')
    def validate_source(self):
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError('Nonblank dataset identity required')
        # Revalidate nested instances, including model_copy updates.
        snapshot = TickerSnapshot.model_validate(self.snapshot.model_dump(mode='json'))
        if snapshot.ticker not in DAILY_UNIVERSE or snapshot.currency != 'USD':
            raise ValueError('Six-stock USD source required; no FX conversion')
        if (snapshot.calendar != 'US_EQUITIES' or snapshot.price_adjustment != 'split_adjusted'
                or snapshot.volume_adjustment != 'split_adjusted'):
            raise ValueError('Explicit split-adjusted US-equity conventions required')
        if sha256(self.raw_payload.encode('utf-8')).hexdigest() != self.raw_sha256:
            raise ValueError('Raw source integrity mismatch')
        if self.source_timestamp is not None and self.source_timestamp > self.retrieved_at:
            raise ValueError('Source timestamp follows retrieval')
        return self

    def as_observed(self) -> ObservedTicker:
        """Retrieval is not completion or trust. All source candles stay provisional."""
        return ObservedTicker(
            snapshot=self.snapshot, fetched_at=self.retrieved_at,
            finality_source='unverified:offline source has no accepted finality evidence',
            availability=tuple(BarAvailability(date=b.date, available_at=self.retrieved_at, final=False)
                               for b in self.snapshot.bars),
        )


class SourceBatch(FrozenModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test'] = 'synthetic_test'
    calendar: CalendarArtifact
    evidence: ProviderEvidenceArtifact | None = None
    observations: tuple[SourceObservation, ...]

    @model_validator(mode='after')
    def complete_batch(self):
        CalendarArtifact.model_validate(self.calendar.model_dump(mode='json'))
        if self.evidence is not None:
            ProviderEvidenceArtifact.model_validate(self.evidence.model_dump(mode='json'))
        if self.calendar.scope != self.scope or (self.evidence is not None and self.evidence.scope != self.scope):
            raise ValueError('Offline artifacts must be synthetic_test')
        if len(self.observations) != 6 or {o.snapshot.ticker for o in self.observations} != set(DAILY_UNIVERSE):
            raise ValueError('Exactly one source observation per six-stock ticker required')
        mapping = {p.ticker: p.exchange for p in self.calendar.listings}
        schedule = self.calendar.as_daily_schedule()
        # Shared session window must be complete, including the latest known session.
        dates = tuple(s.date for s in schedule.sessions)
        identities = set()
        for observation in self.observations:
            observation = SourceObservation.model_validate(observation.model_dump(mode='json'))
            identities.add((observation.snapshot.source, observation.dataset_id, observation.dataset_version))
            if observation.exchange != mapping[observation.snapshot.ticker]:
                raise ValueError('Source exchange differs from calendar mapping')
            if tuple(b.date for b in observation.snapshot.bars) != dates:
                raise ValueError('Missing, stale or unexpected source session coverage')
            if (self.calendar.available_at > observation.retrieved_at
                    or schedule.sessions[-1].closes_at > observation.retrieved_at):
                raise ValueError('Calendar/session retrieval causality violation')
        if len(identities) != 1:
            raise ValueError('Conflicting provider/dataset identities in source batch')
        object.__setattr__(self, 'observations', tuple(sorted(self.observations, key=lambda o: o.snapshot.ticker)))
        return self


class OfflineDailyOHLCVProvider:
    """Implements the existing DailyOHLCVProvider protocol; no parallel pipeline.

    Stored evidence is reference material only. Sprint 1C still requires separate
    reviewed pins and rejects these provisional observations even with pins.
    """

    def __init__(self, batch: SourceBatch):
        self.batch = SourceBatch.model_validate(batch.model_dump(mode='json'))

    def fetch_daily(self, ticker: str, sessions: tuple[Session, ...]) -> ObservedTicker:
        if sessions != self.batch.calendar.as_daily_schedule().sessions:
            raise OfflineProviderError('Requested sessions differ from frozen source coverage')
        for observation in self.batch.observations:
            if observation.snapshot.ticker == ticker:
                return observation.as_observed()
        raise OfflineProviderError(f'Unknown offline ticker: {ticker}')


def assemble_source_batch(provider: SourceProvider, calendar: CalendarArtifact, *, evidence=None) -> SourceBatch:
    """Injected mock source exposes fetch_source(ticker, sessions), with no default transport.

    No persistence occurs until every response passes validation. Provider errors,
    including rate limits, propagate with ticker context and the original cause.
    """
    calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='json'))
    if calendar.scope != 'synthetic_test':
        raise ValueError('Offline ingestion requires a synthetic calendar')
    observations = []
    for ticker in DAILY_UNIVERSE:
        try:
            value = provider.fetch_source(ticker, calendar.as_daily_schedule().sessions)
            value = SourceObservation.model_validate(value.model_dump(mode='json'))
            if value.snapshot.ticker != ticker:
                raise ValueError('Provider ticker mismatch')
            observations.append(value)
        except Exception as exc:
            raise OfflineProviderError(f'Offline source failed for {ticker}') from exc
    return SourceBatch(calendar=calendar, evidence=evidence, observations=tuple(observations))


class SourceSnapshotStore:
    """Separate source archive, not a signal ledger. Atomic immutable dated batches."""

    def __init__(self, path: str | Path):
        self.path = path

    def save(self, batch: SourceBatch) -> str:
        batch = SourceBatch.model_validate(batch.model_dump(mode='json'))
        digest, content = input_hash(batch), canonical_json(batch)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS source_batches '
                       '(sha256 TEXT PRIMARY KEY, session_date TEXT NOT NULL, content TEXT NOT NULL)')
            old = db.execute('SELECT content FROM source_batches WHERE sha256=?', (digest,)).fetchone()
            if old is not None and old[0] != content:
                raise ValueError('Conflicting source archive content')
            db.execute('INSERT OR IGNORE INTO source_batches VALUES (?,?,?)',
                       (digest, batch.calendar.sessions[-1].date.isoformat(), content))
        return digest

    def load(self, *, expected_sha256: str) -> SourceBatch:
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT session_date,content FROM source_batches WHERE sha256=?',
                             (expected_sha256,)).fetchone()
        if row is None:
            raise KeyError(expected_sha256)
        if sha256(row[1].encode('utf-8')).hexdigest() != expected_sha256:
            raise ValueError('Source archive integrity mismatch')
        batch = SourceBatch.model_validate_json(row[1])
        if batch.calendar.sessions[-1].date.isoformat() != row[0] or input_hash(batch) != expected_sha256:
            raise ValueError('Source archive metadata mismatch')
        return batch
