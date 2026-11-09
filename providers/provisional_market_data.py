"""Recorded bytes -> immutable archive -> deterministic PROVISIONAL observations.

No network transport, finality evidence, trust admission, FX or execution.
The supported response is an explicitly versioned offline interchange format,
not a claim to implement any vendor's live response schema.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sqlite3
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from models.daily_signals import DAILY_UNIVERSE, BarAvailability, ObservedTicker, Session
from tools.historical_snapshot import Candle, FrozenModel, TickerSnapshot, canonical_json, input_hash
from tools.market_verification import CalendarArtifact, Exchange

APP_ID = 0x4C4C504F
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_CHAIN = 10000


def _sha(value):
    return sha256(value).hexdigest()


def normalizer_hash():
    root = Path(__file__).resolve().parents[1]
    digest = sha256()
    for name in ('providers/provisional_market_data.py', 'tools/historical_snapshot.py',
                 'models/daily_signals.py', 'tools/market_verification.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    digest.update(json.dumps([platform.python_version(), version('pydantic'), version('tzdata')]).encode())
    return digest.hexdigest()


class ObservationMetadata(FrozenModel):
    schema_version: Literal[1] = 1
    observation_id: str = Field(min_length=1, max_length=128)
    fixture_kind: Literal['synthetic_test', 'licensed_offline']
    licensing_reference: str = Field(min_length=1)  # Supplied evidence reference, NOT a grant.
    provider_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    feed: str = Field(min_length=1)
    ticker: str
    exchange: Exchange
    requested_dates: tuple[date, ...]
    calendar_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    acquired_start: AwareDatetime
    acquired_end: AwareDatetime
    source_timestamp: AwareDatetime | None
    response_id: str | None
    http_status: int = Field(ge=100, le=599, strict=True)
    content_type: str
    encoding: str
    page_count: int = Field(ge=1, strict=True)
    pagination_complete: StrictBool
    retry_after_seconds: int | None = Field(default=None, ge=0, strict=True)
    raw_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    previous_id: str | None = None
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'

    @field_validator('acquired_start', 'acquired_end', 'source_timestamp', mode='before')
    @classmethod
    def explicit_time(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError('Explicit aware timestamp required')
        return value

    @field_validator('requested_dates', mode='before')
    @classmethod
    def plain_dates(cls, value):
        return tuple(Candle.session_date(d) for d in value)

    @field_validator('*', mode='after')
    @classmethod
    def canonical(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Blank observation metadata')
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode='after')
    def valid(self):
        if self.ticker not in DAILY_UNIVERSE:
            raise ValueError('Six-stock observations only')
        if (not self.requested_dates or any(a >= b for a, b in zip(self.requested_dates, self.requested_dates[1:]))
                or self.acquired_start > self.acquired_end
                or (self.source_timestamp is not None and self.source_timestamp > self.acquired_end)
                or self.previous_id == self.observation_id):
            raise ValueError('Invalid observation coverage/chronology/revision')
        return self

    def series_key(self):
        # Dataset versions can change in an explicit revision of the same window.
        return _sha(json.dumps([self.fixture_kind, self.provider_id, self.dataset_id, self.feed, self.ticker,
            [d.isoformat() for d in self.requested_dates]], separators=(',', ':')).encode())


@dataclass(frozen=True)
class RecordedResponse:
    metadata: ObservationMetadata
    body: bytes


class RecordedProvider(Protocol):
    def read_recorded(self, ticker: str, sessions: tuple[Session, ...]) -> RecordedResponse: ...


class NormalizedObservation(FrozenModel):
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    metadata: ObservationMetadata
    observation_sha256: str
    calendar_sha256: str
    as_of: AwareDatetime
    normalizer_sha256: str
    snapshot: TickerSnapshot
    candle_hashes: tuple[str, ...]

    def as_observed(self):
        return ObservedTicker(snapshot=self.snapshot, fetched_at=self.metadata.acquired_end,
            finality_source='unverified:PROVISIONAL recorded acquisition; no completion evidence',
            availability=tuple(BarAvailability(date=b.date, available_at=self.metadata.acquired_end, final=False)
                               for b in self.snapshot.bars))


class ProvisionalBatch(FrozenModel):
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    batch_id: str = Field(min_length=1)
    calendar: CalendarArtifact
    as_of: AwareDatetime
    observations: tuple[NormalizedObservation, ...]

    @model_validator(mode='after')
    def complete(self):
        if len(self.observations) != 6 or tuple(o.metadata.ticker for o in self.observations) != DAILY_UNIVERSE:
            raise ValueError('Complete canonical six-stock batch required')
        sources = {(o.metadata.provider_id, o.metadata.dataset_id, o.metadata.dataset_version,
                    o.metadata.feed, o.metadata.fixture_kind, o.metadata.licensing_reference) for o in self.observations}
        if len(sources) != 1:
            raise ValueError('Mixed source/dataset/license batch')
        return self


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def _context(calendar, as_of):
    calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='json'))
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('Explicit aware as-of time required')
    as_of = as_of.astimezone(timezone.utc)
    sessions = calendar.as_daily_schedule().completed_sessions(as_of)
    if len(sessions) < 200:
        raise ValueError('At least 200 completed sessions required')
    return calendar, as_of, sessions


def normalize_recorded(record, calendar, *, as_of):
    """Pure, no repair/trim/fill/adjustment inference; finality is always absent."""
    meta = ObservationMetadata.model_validate(record.metadata.model_dump(mode='json'))
    body = record.body
    if type(body) is not bytes or len(body) > MAX_RAW_BYTES or _sha(body) != meta.raw_sha256:
        raise ValueError('Raw response integrity/size mismatch')
    calendar, as_of, sessions = _context(calendar, as_of)
    mapping = {r.ticker: r.exchange for r in calendar.listings}
    if (meta.calendar_sha256 != input_hash(calendar) or mapping[meta.ticker] != meta.exchange
            or meta.requested_dates != tuple(s.date for s in sessions)
            or meta.acquired_end > as_of or meta.acquired_start < sessions[-1].closes_at
            or (meta.fixture_kind == 'synthetic_test') != (calendar.scope == 'synthetic_test')):
        raise ValueError('Calendar, scope, session or acquisition chronology mismatch')
    if (meta.http_status != 200 or meta.content_type != 'application/json' or meta.encoding != 'utf-8'
            or not meta.pagination_complete or meta.page_count != 1):
        raise ValueError('Unsupported/error/incomplete recorded response')
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON number')
    data = json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
        parse_float=Decimal, parse_constant=invalid_constant)
    fields = {'format', 'provider_id', 'dataset_id', 'dataset_version', 'feed', 'ticker', 'exchange',
              'currency', 'price_adjustment', 'volume_adjustment', 'dividend_convention', 'split_convention', 'bars'}
    if not isinstance(data, dict) or set(data) != fields or data['format'] != 'recorded_ohlcv_v1':
        raise ValueError('Unsupported/ambiguous recorded response schema')
    for key in ('provider_id', 'dataset_id', 'dataset_version', 'feed', 'ticker', 'exchange'):
        if data[key] != getattr(meta, key):
            raise ValueError('Response source/instrument identity mismatch')
    expected = dict(currency='USD', price_adjustment='split_adjusted', volume_adjustment='split_adjusted',
        dividend_convention='recorded_not_applied', split_convention='events_recorded_prices_adjusted')
    if any(data[k] != v for k, v in expected.items()):
        raise ValueError('Unsupported currency/adjustment conventions')
    if not isinstance(data['bars'], list):
        raise ValueError('Explicit bar list required')
    bars = []
    numeric = {'open', 'high', 'low', 'close', 'volume', 'dividend', 'split_ratio'}
    for row in data['bars']:
        if not isinstance(row, dict) or set(row) != numeric | {'date'}:
            raise ValueError('Missing/extra candle fields or corporate actions')
        if any(type(row[k]) not in (int, Decimal) for k in numeric):
            raise ValueError('Unambiguous JSON numeric candle fields required')
        bars.append(Candle(date=row['date'], **{k: float(row[k]) for k in numeric}))
    if tuple(b.date for b in bars) != meta.requested_dates:
        raise ValueError('Missing, duplicate, unordered or unexpected sessions')
    snapshot = TickerSnapshot(ticker=meta.ticker, source=meta.provider_id, calendar='US_EQUITIES',
        bars=tuple(bars), **expected)
    return NormalizedObservation(metadata=meta, observation_sha256=_sha(canonical_json(meta).encode() + b'\0' + body),
        calendar_sha256=input_hash(calendar), as_of=as_of, normalizer_sha256=normalizer_hash(),
        snapshot=snapshot, candle_hashes=tuple(input_hash(b) for b in bars))


class ProvisionalArchive:
    """Separate application database; append-only API, hashes are not signatures."""
    def __init__(self, path):
        self.path = Path(path)
        with closing(self._connect(create=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables and app == 0 and version == 0:
                db.execute('CREATE TABLE observations (sequence INTEGER PRIMARY KEY, observation_id TEXT UNIQUE NOT NULL, series_key TEXT NOT NULL, previous_id TEXT REFERENCES observations(observation_id), metadata_json TEXT NOT NULL, body BLOB NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE normalization (observation_id TEXT REFERENCES observations(observation_id), context_sha256 TEXT, content TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(observation_id,context_sha256))')
                db.execute('CREATE TABLE batches (batch_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE conflicts (observation_id TEXT, previous_id TEXT, content TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(observation_id,previous_id,sha256))')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
            elif app != APP_ID or version != 1:
                raise ValueError('Not a supported provisional archive; no migration/repair')
            # Missing existing schema is never silently recreated.
            for name in ('observations', 'normalization', 'batches', 'conflicts'):
                db.execute(f'SELECT * FROM {name} LIMIT 0')
            db.execute('COMMIT')

    def _connect(self, *, create=False):
        db = sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                             uri=True, isolation_level=None, timeout=2)
        try:
            if not create and (db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('Incompatible provisional archive identity')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    def _load(self, db, identity):
        seen = set()
        first, child = None, None
        while identity is not None:
            if identity in seen or len(seen) >= MAX_CHAIN:
                raise ValueError('Invalid revision chain')
            seen.add(identity)
            row = db.execute('SELECT series_key,previous_id,metadata_json,body,sha256 FROM observations WHERE observation_id=?', (identity,)).fetchone()
            if row is None:
                raise ValueError('Missing observation/revision evidence')
            meta = ObservationMetadata.model_validate_json(row[2])
            body = row[3]
            if (meta.observation_id != identity or meta.previous_id != row[1] or meta.series_key() != row[0]
                    or _sha(body) != meta.raw_sha256 or canonical_json(meta) != row[2]
                    or _sha(row[2].encode() + b'\0' + body) != row[4]):
                raise ValueError('Archive observation integrity mismatch')
            if child and (child.series_key() != meta.series_key() or child.acquired_end < meta.acquired_end):
                raise ValueError('Revision lineage/chronology conflict')
            first = first or RecordedResponse(meta, body)
            child, identity = meta, meta.previous_id
        return first

    def load(self, identity):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            return self._load(db, identity)

    def record(self, response):
        meta = ObservationMetadata.model_validate(response.metadata.model_dump(mode='json'))
        body = response.body
        if type(body) is not bytes or len(body) > MAX_RAW_BYTES or _sha(body) != meta.raw_sha256:
            raise ValueError('Raw response integrity/size mismatch')
        content = canonical_json(meta)
        digest = _sha(content.encode() + b'\0' + body)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT sha256 FROM observations WHERE observation_id=?', (meta.observation_id,)).fetchone()
            if old:
                self._load(db, meta.observation_id)
                if old[0] != digest:
                    raise ValueError('Observation ID conflict; no overwrite')
            else:
                head = db.execute('SELECT observation_id FROM observations WHERE series_key=? ORDER BY sequence DESC LIMIT 1', (meta.series_key(),)).fetchone()
                if meta.previous_id != (head[0] if head else None):
                    raise ValueError('Explicit current predecessor required; revision conflict')
                if head:
                    previous = self._load(db, head[0]).metadata
                    if meta.acquired_end < previous.acquired_end:
                        raise ValueError('Revision acquisition time predates predecessor')
                db.execute('INSERT INTO observations (observation_id,series_key,previous_id,metadata_json,body,sha256) VALUES (?,?,?,?,?,?)',
                    (meta.observation_id, meta.series_key(), meta.previous_id, content, body, digest))
            db.execute('COMMIT')
        return digest

    def normalize(self, identity, calendar, *, as_of):
        calendar, as_of, _ = _context(calendar, as_of)
        context = _sha((input_hash(calendar) + as_of.isoformat() + normalizer_hash()).encode())
        try:
            result = normalize_recorded(self.load(identity), calendar, as_of=as_of)
            content = canonical_json(result)
        except Exception as exc:
            content = json.dumps({'status': 'FAILED', 'error_type': type(exc).__name__}, sort_keys=True)
            try:
                self._result(identity, context, content)
            except Exception as audit_error:
                exc.add_note('Normalization failure evidence could not be committed: ' + type(audit_error).__name__)
            raise
        self._result(identity, context, content)
        return result

    def _result(self, identity, context, content):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            self._load(db, identity)
            old = db.execute('SELECT content,sha256 FROM normalization WHERE observation_id=? AND context_sha256=?', (identity, context)).fetchone()
            if old and old != (content, _sha(content.encode())):
                raise ValueError('Normalization/replay integrity conflict')
            if not old:
                db.execute('INSERT INTO normalization VALUES (?,?,?,?)', (identity, context, content, _sha(content.encode())))
                current = json.loads(content)
                if current['status'] == 'PROVISIONAL':
                    current = NormalizedObservation.model_validate(current)
                    # Compare normalized, overlapping windows, not only identical
                    # raw request windows. Conflict is evidence, never finality.
                    for prior_id, prior_content, prior_sha in db.execute(
                            'SELECT observation_id,content,sha256 FROM normalization WHERE observation_id!=?', (identity,)).fetchall():
                        if _sha(prior_content.encode()) != prior_sha:
                            raise ValueError('Prior normalization integrity conflict')
                        prior_data = json.loads(prior_content)
                        if prior_data['status'] != 'PROVISIONAL':
                            continue
                        prior = NormalizedObservation.model_validate(prior_data)
                        keys = ('fixture_kind', 'provider_id', 'dataset_id', 'feed', 'ticker')
                        if any(getattr(prior.metadata, k) != getattr(current.metadata, k) for k in keys):
                            continue
                        self._load(db, prior_id)
                        previous = {b.date: input_hash(b) for b in prior.snapshot.bars}
                        differences = [b.date.isoformat() for b in current.snapshot.bars
                                       if b.date in previous and previous[b.date] != input_hash(b)]
                        if differences:
                            evidence = json.dumps(dict(observation_id=identity, previous_id=prior_id,
                                current_sha256=_sha(content.encode()), previous_sha256=prior_sha,
                                changed_dates=differences), sort_keys=True, separators=(',', ':'))
                            existing = db.execute('SELECT content,sha256 FROM conflicts WHERE observation_id=? AND previous_id=? AND sha256=?',
                                (identity, prior_id, _sha(evidence.encode()))).fetchone()
                            if existing and existing != (evidence, _sha(evidence.encode())):
                                raise ValueError('Conflicting revision evidence; no overwrite')
                            if not existing:
                                db.execute('INSERT INTO conflicts VALUES (?,?,?,?)', (identity, prior_id, evidence, _sha(evidence.encode())))
            db.execute('COMMIT')

    def conflicts(self, identity):
        """Durable detected revisions across overlapping windows, with raw links."""
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            self._load(db, identity)
            result = []
            for prior_id, content, digest in db.execute('SELECT previous_id,content,sha256 FROM conflicts WHERE observation_id=? ORDER BY previous_id', (identity,)):
                evidence = json.loads(content)
                if (_sha(content.encode()) != digest or evidence['observation_id'] != identity
                        or evidence['previous_id'] != prior_id):
                    raise ValueError('Revision evidence integrity mismatch')
                for obs_id, key in ((identity, 'current_sha256'), (prior_id, 'previous_sha256')):
                    self._load(db, obs_id)
                    row = db.execute('SELECT content FROM normalization WHERE observation_id=? AND sha256=?', (obs_id, evidence[key])).fetchone()
                    if not row or _sha(row[0].encode()) != evidence[key]:
                        raise ValueError('Missing/inconsistent revision normalization evidence')
                result.append(evidence)
            return tuple(result)

    def _check_result(self, db, actual):
        context = _sha((actual.calendar_sha256 + actual.as_of.isoformat() + actual.normalizer_sha256).encode())
        row = db.execute('SELECT content,sha256 FROM normalization WHERE observation_id=? AND context_sha256=?',
            (actual.metadata.observation_id, context)).fetchone()
        content = canonical_json(actual)
        if row != (content, _sha(content.encode())):
            raise ValueError('Missing/inconsistent normalization evidence')

    def save_batch(self, batch):
        # Recompute everything from archived raw bytes. Never trust constructed
        # models or a caller's claimed complete normalized batch.
        batch = ProvisionalBatch.model_validate(batch.model_dump(mode='json'))
        calendar, as_of, _ = _context(batch.calendar, batch.as_of)
        content = canonical_json(batch)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for observation in batch.observations:
                actual = normalize_recorded(self._load(db, observation.metadata.observation_id), calendar, as_of=as_of)
                if actual != observation:
                    raise ValueError('Batch differs from archived replay')
                self._check_result(db, actual)
            old = db.execute('SELECT content,sha256 FROM batches WHERE batch_id=?', (batch.batch_id,)).fetchone()
            if old and old != (content, _sha(content.encode())):
                raise ValueError('Batch ID or evidence integrity conflict')
            if not old:
                db.execute('INSERT INTO batches VALUES (?,?,?)', (batch.batch_id, content, _sha(content.encode())))
            db.execute('COMMIT')
        return input_hash(batch)

    def load_batch(self, batch_id, *, expected_sha256):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT content,sha256 FROM batches WHERE batch_id=?', (batch_id,)).fetchone()
            if row is None or _sha(row[0].encode()) != row[1] or row[1] != expected_sha256:
                raise ValueError('Missing/inconsistent complete batch evidence')
            batch = ProvisionalBatch.model_validate_json(row[0])
            if batch.batch_id != batch_id:
                raise ValueError('Batch identity conflict')
            for observation in batch.observations:
                actual = normalize_recorded(self._load(db, observation.metadata.observation_id), batch.calendar, as_of=batch.as_of)
                if observation != actual:
                    raise ValueError('Offline replay differs from archived batch')
                self._check_result(db, actual)
            return batch


def acquire_recorded_batch(provider: RecordedProvider, archive: ProvisionalArchive, calendar, *, as_of, batch_id):
    calendar, as_of, sessions = _context(calendar, as_of)
    observations = []
    for ticker in DAILY_UNIVERSE:
        response = provider.read_recorded(ticker, sessions)
        archive.record(response)  # Invalid/error bodies are retained before normalization.
        if response.metadata.ticker != ticker:
            raise ValueError('Recorded provider returned another ticker')
        observations.append(archive.normalize(response.metadata.observation_id, calendar, as_of=as_of))
    batch = ProvisionalBatch(batch_id=batch_id, calendar=calendar, as_of=as_of, observations=tuple(observations))
    archive.save_batch(batch)
    return batch


class ProvisionalDailyProvider:
    """Existing DailyOHLCVProvider boundary, always returns final=False."""
    def __init__(self, archive, batch_id, *, expected_sha256):
        self.batch = archive.load_batch(batch_id, expected_sha256=expected_sha256)

    def fetch_daily(self, ticker, sessions):
        expected = self.batch.calendar.as_daily_schedule().completed_sessions(self.batch.as_of)
        if sessions != expected:
            raise ValueError('Requested sessions differ from archived batch')
        for observation in self.batch.observations:
            if observation.metadata.ticker == ticker:
                return observation.as_observed()
        raise ValueError('Unknown six-stock ticker')
