"""Pinned offline calendar and provider-evidence verification; no calendar inference."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from models.daily_signals import DAILY_UNIVERSE, DailySignalInputs, Session, SessionSchedule
from tools.historical_snapshot import Candle, FrozenModel, input_hash


NEW_YORK = ZoneInfo('America/New_York')
Exchange = Literal['XNYS', 'XNAS']
Scope = Literal['real', 'synthetic_test']


class VersionedRecord(FrozenModel):
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @field_validator('source', 'version')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Nonblank source/version required')
        return value


class ExchangeSession(Session):
    exchange: Exchange
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @model_validator(mode='after')
    def new_york_dates(self):
        if self.opens_at.astimezone(NEW_YORK).date() != self.date or self.closes_at.astimezone(NEW_YORK).date() != self.date:
            raise ValueError('Session timestamps must match America/New_York trading date')
        return self


class ClosedDate(VersionedRecord):
    date: date
    exchange: Exchange
    reason: Literal['weekend', 'holiday', 'exceptional_closure', 'other_official_closure']

    @field_validator('date', mode='before')
    @classmethod
    def plain_date(cls, value):
        return Candle.session_date(value)


class Listing(FrozenModel):
    ticker: str
    exchange: Exchange


class CalendarArtifact(VersionedRecord):
    schema_version: Literal[1]
    scope: Scope
    available_at: AwareDatetime
    coverage_start: date
    coverage_end: date  # Exclusive New York local date.
    listings: tuple[Listing, ...]
    sessions: tuple[ExchangeSession, ...]
    closed_dates: tuple[ClosedDate, ...]

    @field_validator('coverage_start', 'coverage_end', mode='before')
    @classmethod
    def plain_date(cls, value):
        return Candle.session_date(value)

    @field_validator('available_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def complete_artifact(self):
        if not self.coverage_start < self.coverage_end:
            raise ValueError('Calendar coverage must be nonempty and end-exclusive')
        if len(self.listings) != 6 or {p.ticker for p in self.listings} != set(DAILY_UNIVERSE):
            raise ValueError('A versioned exchange mapping for all six tickers is required')
        exchanges = {p.exchange for p in self.listings}
        seen = set()
        prior = {}
        for session in self.sessions:
            if session.exchange in prior and session.date <= prior[session.exchange]:
                raise ValueError('Exchange sessions must be unique and chronological')
            prior[session.exchange] = session.date
        for record in (*self.sessions, *self.closed_dates):
            key = (record.exchange, record.date)
            if (key in seen or record.exchange not in exchanges
                    or not self.coverage_start <= record.date < self.coverage_end):
                raise ValueError('Duplicate, inconsistent or out-of-coverage calendar record')
            if (record.source, record.version) != (self.source, self.version):
                raise ValueError('Session source/version differs from artifact')
            seen.add(key)
        day = self.coverage_start
        while day < self.coverage_end:
            if any((exchange, day) not in seen for exchange in exchanges):
                raise ValueError('Missing calendar date: explicit open/closed status required')
            day += timedelta(days=1)
        object.__setattr__(self, 'listings', tuple(sorted(self.listings, key=lambda p: p.ticker)))
        object.__setattr__(self, 'sessions', tuple(sorted(self.sessions, key=lambda p: (p.exchange, p.date))))
        object.__setattr__(self, 'closed_dates', tuple(sorted(self.closed_dates, key=lambda p: (p.exchange, p.date))))
        return self

    def as_daily_schedule(self) -> SessionSchedule:
        """Adapt to 1B, never generate holidays or guess closing times.

        1B requires a common calendar. Divergent exchange sessions fail closed.
        """
        groups = []
        for exchange in sorted({p.exchange for p in self.listings}):
            groups.append(tuple(Session(date=s.date, opens_at=s.opens_at, closes_at=s.closes_at)
                                for s in self.sessions if s.exchange == exchange))
        if not groups or any(group != groups[0] for group in groups[1:]):
            raise ValueError('Divergent exchange sessions cannot use the shared 1B calendar')
        return SessionSchedule(
            schema_version=1, calendar='US_EQUITIES', source=f'{self.source}@{self.version}',
            available_at=self.available_at,
            coverage_start=datetime.combine(self.coverage_start, time(), NEW_YORK),
            coverage_end=datetime.combine(self.coverage_end, time(), NEW_YORK), sessions=groups[0],
        )


class CandleEvidence(FrozenModel):
    ticker: str
    exchange: Exchange
    date: date
    candle_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_id: str = Field(min_length=1)
    issued_at: AwareDatetime
    official_close: AwareDatetime
    provider_final: StrictBool
    completed_session: StrictBool

    @field_validator('date', mode='before')
    @classmethod
    def plain_date(cls, value):
        return Candle.session_date(value)

    @field_validator('issued_at', 'official_close')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)


class ProviderEvidenceArtifact(VersionedRecord):
    schema_version: Literal[1]
    scope: Scope
    available_at: AwareDatetime
    candles: tuple[CandleEvidence, ...]

    @field_validator('available_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def unique_evidence(self):
        keys = [(e.ticker, e.date) for e in self.candles]
        if len(set(keys)) != len(keys) or len({e.evidence_id for e in self.candles}) != len(keys):
            raise ValueError('Duplicate candle evidence or evidence identifier')
        if any(not e.evidence_id.strip() or e.issued_at > self.available_at for e in self.candles):
            raise ValueError('Invalid evidence identifier or availability chronology')
        object.__setattr__(self, 'candles', tuple(sorted(self.candles, key=lambda e: (e.ticker, e.date))))
        return self


class TrustPin(VersionedRecord):
    kind: Literal['calendar', 'provider_evidence']
    scope: Scope
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1)

    @field_validator('review_reference')
    @classmethod
    def reviewed(cls, value):
        if not value.strip():
            raise ValueError('External authority review reference required')
        return value


class TrustRegistry(FrozenModel):
    """An external caller-controlled root, never accepted from the run itself."""
    mode: Scope = 'real'
    pins: tuple[TrustPin, ...] = ()

    def require(self, artifact, kind: str):
        if artifact.scope != self.mode:
            raise ValueError('Synthetic evidence cannot be used as real-world authority')
        digest = input_hash(artifact)
        if not any((pin.kind, pin.scope, pin.source, pin.version, pin.sha256) == (
            kind, artifact.scope, artifact.source, artifact.version, digest,
        ) for pin in self.pins):
            raise ValueError(f'Untrusted {kind}: externally reviewed exact-content pin required')


class VerificationPolicy(FrozenModel):
    publication_delay_seconds: int = Field(ge=0, strict=True)
    method: Literal['pinned_completed_session_evidence_v1'] = 'pinned_completed_session_evidence_v1'


class CandleVerification(VersionedRecord):
    ticker: str
    date: date
    exchange: Exchange
    official_close: AwareDatetime
    verified_at: AwareDatetime
    method: Literal['pinned_completed_session_evidence_v1']
    evidence_id: str
    evidence_source: str
    evidence_version: str
    evidence_sha256: str
    candle_sha256: str


def verify_candle_finality(
    inputs: DailySignalInputs, calendar: CalendarArtifact, evidence: ProviderEvidenceArtifact, *,
    policy: VerificationPolicy, verified_at: datetime, trust: TrustRegistry,
) -> tuple[CandleVerification, ...]:
    """Named verifier: time is necessary, but never sufficient, for finality."""
    inputs = DailySignalInputs.model_validate(inputs.model_dump(mode='json'))
    calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='json'))
    evidence = ProviderEvidenceArtifact.model_validate(evidence.model_dump(mode='json'))
    trust = TrustRegistry.model_validate(trust.model_dump(mode='json'))
    policy = VerificationPolicy.model_validate(policy.model_dump(mode='json'))
    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ValueError('Timezone-aware verification time required')
    verified_at = verified_at.astimezone(timezone.utc)
    trust.require(calendar, 'calendar')
    trust.require(evidence, 'provider_evidence')
    if not calendar.available_at <= verified_at <= inputs.decision_at or evidence.available_at > verified_at:
        raise ValueError('Verification/authority availability violates decision causality')
    schedule = calendar.as_daily_schedule()
    schedule.completed_sessions(verified_at)  # Coverage at verification, not merely decision time.
    if schedule != inputs.schedule:
        raise ValueError('Frozen schedule differs from the pinned authoritative artifact')
    listing = {p.ticker: p.exchange for p in calendar.listings}
    sessions = {(s.exchange, s.date): s for s in calendar.sessions}
    proofs = {(e.ticker, e.date): e for e in evidence.candles}
    expected = {(t.ticker, b.date) for t in inputs.snapshot.tickers for b in t.bars}
    if set(proofs) != expected:
        raise ValueError('Exact evidence coverage for every candle and all six tickers required')
    observed = {o.snapshot.ticker: o for o in inputs.observed}
    if any(o.fetched_at > verified_at for o in inputs.observed):
        raise ValueError('Verification cannot precede observation fetch completion')
    records = []
    for ticker in inputs.snapshot.tickers:
        if ticker.source != evidence.source:
            raise ValueError('Provider evidence source does not match frozen dataset source')
        for bar in ticker.bars:
            # Reuse the V1 candle validator, including finite OHLCV relationships.
            bar = Candle.model_validate(bar.model_dump(mode='json'))
            session = sessions.get((listing[ticker.ticker], bar.date))
            proof = proofs[(ticker.ticker, bar.date)]
            if session is None:
                raise ValueError('Candle date is not an authoritative trading session')
            if proof.exchange != session.exchange or proof.official_close != session.closes_at:
                raise ValueError('Evidence exchange/official close mismatch')
            if not proof.provider_final or not proof.completed_session:
                raise ValueError('Insufficient provider completion evidence')
            if proof.candle_sha256 != input_hash(bar):
                raise ValueError('Provider evidence is for a different candle')
            if (verified_at <= session.closes_at
                    or verified_at < session.closes_at + timedelta(seconds=policy.publication_delay_seconds)):
                raise ValueError('Official close/publication delay has not elapsed')
            if not session.closes_at <= proof.issued_at <= observed[ticker.ticker].fetched_at:
                raise ValueError('Provider evidence issuance violates candle/fetch causality')
            records.append(CandleVerification(
                source=calendar.source, version=calendar.version, ticker=ticker.ticker, date=bar.date,
                exchange=session.exchange, official_close=session.closes_at, verified_at=verified_at,
                method=policy.method, evidence_id=proof.evidence_id, evidence_source=evidence.source,
                evidence_version=evidence.version, evidence_sha256=input_hash(proof), candle_sha256=input_hash(bar),
            ))
    return tuple(records)
