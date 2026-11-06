from datetime import date, datetime, time, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from models.daily_signals import DAILY_UNIVERSE, BarAvailability, ObservedTicker
from tools.daily_signal_pipeline import DailySignalStore, freeze_daily_inputs
from tools.historical_snapshot import Candle, TickerSnapshot, canonical_json, input_hash
from tools.market_verification import (
    CalendarArtifact, CandleEvidence, ClosedDate, ExchangeSession, Listing,
    ProviderEvidenceArtifact, TrustPin, TrustRegistry, VerificationPolicy,
)
from tools.verified_daily_pipeline import (
    VerifiedDailyInputs, freeze_verified_daily_inputs, ingest_verified_daily_signals,
    load_verified_daily_signals, publish_verified_daily_signals, replay_verified_daily_signals,
)


NY = ZoneInfo('America/New_York')
CALENDAR_SOURCE = 'SYNTHETIC-ONLY-calendar'
PROVIDER_SOURCE = 'SYNTHETIC-ONLY-provider'


def registry(calendar, evidence):
    return TrustRegistry(mode='synthetic_test', pins=tuple(TrustPin(
        kind=kind, source=value.source, version=value.version, scope='synthetic_test',
        sha256=input_hash(value), review_reference='TEST FIXTURE ONLY; NOT EXCHANGE AUTHORITY',
    ) for kind, value in (('calendar', calendar), ('provider_evidence', evidence))))


@pytest.fixture(scope='module')
def fixture():
    # These are invented TEST dates/times, explicitly never official market data.
    start, end = date(2020, 1, 1), date(2020, 11, 11)
    sessions, closed = [], []
    day = start
    while day < end:
        for exchange in ('XNAS', 'XNYS'):
            reason = ('weekend' if day.weekday() >= 5 else 'holiday' if day == start
                      else 'exceptional_closure' if day == date(2020, 2, 12) else None)
            if reason:
                closed.append(ClosedDate(date=day, exchange=exchange, reason=reason,
                                         source=CALENDAR_SOURCE, version='fixture-1'))
            else:
                close = time(13) if day == date(2020, 2, 14) else time(16)
                sessions.append(ExchangeSession(
                    date=day, exchange=exchange, source=CALENDAR_SOURCE, version='fixture-1',
                    opens_at=datetime.combine(day, time(9, 30), NY),
                    closes_at=datetime.combine(day, close, NY),
                ))
        day += timedelta(days=1)
    calendar = CalendarArtifact(
        schema_version=1, scope='synthetic_test', source=CALENDAR_SOURCE, version='fixture-1',
        available_at=datetime(2019, 12, 1, tzinfo=timezone.utc), coverage_start=start, coverage_end=end,
        listings=tuple(Listing(ticker=t, exchange='XNAS' if i % 2 else 'XNYS')
                       for i, t in enumerate(DAILY_UNIVERSE)),
        sessions=tuple(sessions), closed_dates=tuple(closed),
    )
    schedule = calendar.as_daily_schedule()
    fetched = schedule.sessions[-1].closes_at + timedelta(minutes=10)
    verified = fetched + timedelta(minutes=5)
    decision = verified + timedelta(minutes=5)
    observed, proofs = [], []
    mapping = {p.ticker: p.exchange for p in calendar.listings}
    for ticker in DAILY_UNIVERSE:
        bars = tuple(Candle(date=s.date, open=100, high=101, low=99, close=100,
                            volume=1000, dividend=0, split_ratio=1) for s in schedule.sessions)
        observed.append(ObservedTicker(
            snapshot=TickerSnapshot(ticker=ticker, currency='USD', source=PROVIDER_SOURCE,
                calendar='US_EQUITIES', price_adjustment='split_adjusted', volume_adjustment='split_adjusted',
                dividend_convention='recorded_not_applied', split_convention='events_recorded_prices_adjusted', bars=bars),
            fetched_at=fetched, finality_source='synthetic explicitly attested completion',
            availability=tuple(BarAvailability(date=b.date, available_at=fetched, final=True) for b in bars),
        ))
        for bar, session in zip(bars, schedule.sessions):
            proofs.append(CandleEvidence(
                ticker=ticker, exchange=mapping[ticker], date=bar.date,
                candle_sha256=input_hash(bar), evidence_id=f'synthetic:{ticker}:{bar.date}',
                issued_at=session.closes_at + timedelta(minutes=1), official_close=session.closes_at,
                provider_final=True, completed_session=True,
            ))
    evidence = ProviderEvidenceArtifact(
        schema_version=1, scope='synthetic_test', source=PROVIDER_SOURCE, version='fixture-1',
        available_at=schedule.sessions[-1].closes_at + timedelta(minutes=2), candles=tuple(proofs),
    )
    return calendar, tuple(observed), evidence, verified, decision


def freeze(fixture, **overrides):
    calendar, observed, evidence, verified, decision = fixture
    settings = dict(policy=VerificationPolicy(publication_delay_seconds=600),
                    verified_at=verified, decision_at=decision, trust=registry(calendar, evidence))
    settings.update(overrides)
    return freeze_verified_daily_inputs(calendar, observed, evidence, **settings)


def replay(inputs, fixture, trust=None):
    return replay_verified_daily_signals(inputs, expected_sha256=input_hash(inputs),
        trust=registry(fixture[0], fixture[2]) if trust is None else trust)


def test_normal_sessions_and_complete_provenance(fixture):
    inputs = freeze(fixture)
    report = replay(inputs, fixture)
    assert report.scope == 'synthetic_test'
    assert len(report.daily_report.decisions) == 12
    assert len(report.records) == 6 * len(fixture[1][0].snapshot.bars)
    record = report.records[-1]
    assert record.method == 'pinned_completed_session_evidence_v1'
    assert record.source == CALENDAR_SOURCE and record.version == 'fixture-1'
    assert record.evidence_source == PROVIDER_SOURCE
    assert record.evidence_id.startswith('synthetic:')
    assert len(record.evidence_sha256) == len(record.candle_sha256) == 64
    assert record.official_close < record.verified_at <= report.daily_report.decision_at


def test_weekends_holidays_and_exceptional_closures_are_explicit(fixture):
    calendar = fixture[0]
    schedule = calendar.as_daily_schedule()
    dates = {s.date for s in schedule.sessions}
    assert date(2020, 1, 4) not in dates
    assert date(2020, 1, 1) not in dates
    assert date(2020, 2, 12) not in dates  # Synthetic exceptional closure, not a real claim.
    assert {c.reason for c in calendar.closed_dates} >= {'weekend', 'holiday', 'exceptional_closure'}


def test_early_close_and_both_dst_transitions(fixture):
    sessions = {s.date: s for s in fixture[0].as_daily_schedule().sessions}
    assert sessions[date(2020, 2, 14)].closes_at.hour == 18  # Synthetic 13:00 EST early close.
    assert sessions[date(2020, 3, 6)].closes_at.hour == 21
    assert sessions[date(2020, 3, 9)].closes_at.hour == 20
    assert sessions[date(2020, 10, 30)].closes_at.hour == 20
    assert sessions[date(2020, 11, 2)].closes_at.hour == 21
    assert all(s.closes_at.astimezone(NY).hour == 16 for d, s in sessions.items() if d != date(2020, 2, 14))


@pytest.mark.parametrize('change', ['missing_date', 'duplicate_session', 'unordered', 'wrong_version', 'naive', 'wrong_date'])
def test_invalid_calendar_records(fixture, change):
    data = fixture[0].model_dump(mode='json')
    if change == 'missing_date':
        data['closed_dates'].pop()
    elif change == 'duplicate_session':
        data['sessions'].insert(1, data['sessions'][0])
    elif change == 'unordered':
        data['sessions'][0], data['sessions'][1] = data['sessions'][1], data['sessions'][0]
    elif change == 'wrong_version':
        data['sessions'][0]['version'] = 'other'
    elif change == 'naive':
        data['sessions'][0]['closes_at'] = '2020-01-02T16:00:00'
    else:
        data['sessions'][0]['closes_at'] = '2020-01-03T01:00:00Z'
    with pytest.raises(ValueError):
        CalendarArtifact.model_validate(data)


def test_missing_coverage_fails_without_falling_back(fixture):
    with pytest.raises(ValueError, match='cover decision time'):
        freeze(fixture, decision_at=datetime(2021, 1, 1, tzinfo=timezone.utc))


def test_divergent_exchanges_fail_instead_of_silently_intersecting(fixture):
    data = fixture[0].model_dump(mode='json')
    record = next(s for s in data['sessions'] if s['exchange'] == 'XNYS')
    record['closes_at'] = record['closes_at'].replace('21:00', '20:00')
    with pytest.raises(ValueError, match='Divergent exchange'):
        CalendarArtifact.model_validate(data).as_daily_schedule()


def test_empty_default_real_trust_and_cross_scope_rejection(fixture):
    with pytest.raises(ValueError):
        freeze(fixture, trust=TrustRegistry())
    with pytest.raises(ValueError, match='Synthetic evidence'):
        freeze(fixture, trust=TrustRegistry(mode='real', pins=registry(fixture[0], fixture[2]).pins))
    with pytest.raises(ValueError, match='Untrusted'):
        freeze(fixture, trust=TrustRegistry(mode='synthetic_test'))


@pytest.mark.parametrize('kind', ['calendar', 'provider_evidence'])
def test_correct_source_name_is_not_a_trust_pin(fixture, kind):
    data = registry(fixture[0], fixture[2]).model_dump(mode='json')
    for pin in data['pins']:
        if pin['kind'] == kind:
            pin['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='Untrusted'):
        freeze(fixture, trust=TrustRegistry.model_validate(data))


@pytest.mark.parametrize('change', ['absent', 'not_final', 'incomplete', 'wrong_hash', 'wrong_close', 'wrong_exchange', 'before_close', 'future_evidence'])
def test_provider_evidence_must_be_sufficient_even_when_pinned(fixture, change):
    data = fixture[2].model_dump(mode='json')
    proof = data['candles'][-1]
    if change == 'absent':
        data['candles'].pop()
    elif change == 'not_final':
        proof['provider_final'] = False
    elif change == 'incomplete':
        proof['completed_session'] = False
    elif change == 'wrong_hash':
        proof['candle_sha256'] = '0' * 64
    elif change == 'wrong_close':
        proof['official_close'] = (fixture[0].as_daily_schedule().sessions[-1].closes_at - timedelta(hours=1)).isoformat()
    elif change == 'wrong_exchange':
        proof['exchange'] = 'XNYS' if proof['exchange'] == 'XNAS' else 'XNAS'
    elif change == 'before_close':
        proof['issued_at'] = (fixture[0].as_daily_schedule().sessions[-1].closes_at - timedelta(seconds=1)).isoformat()
    else:
        data['available_at'] = (fixture[4] + timedelta(minutes=1)).isoformat()
    evidence = ProviderEvidenceArtifact.model_validate(data)
    changed = (fixture[0], fixture[1], evidence, fixture[3], fixture[4])
    with pytest.raises(ValueError):
        freeze(changed)


def test_publication_delay_and_verification_causality(fixture):
    with pytest.raises(ValueError, match='delay'):
        freeze(fixture, policy=VerificationPolicy(publication_delay_seconds=3600))
    with pytest.raises(ValueError):
        freeze(fixture, verified_at=fixture[0].as_daily_schedule().sessions[-1].closes_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match='fetch completion'):
        freeze(fixture, verified_at=fixture[1][0].fetched_at - timedelta(seconds=1),
               policy=VerificationPolicy(publication_delay_seconds=0))
    with pytest.raises(ValueError):
        freeze(fixture, verified_at=fixture[4] + timedelta(seconds=1))


def test_yahoo_like_delayed_response_cannot_replace_evidence(fixture):
    calendar, observed, _, verified, decision = fixture
    empty = ProviderEvidenceArtifact(schema_version=1, scope='synthetic_test', source=PROVIDER_SOURCE,
                                     version='fixture-1', available_at=verified, candles=())
    with pytest.raises(ValueError, match='Exact evidence coverage'):
        freeze((calendar, observed, empty, verified, decision))


def test_provisional_candle_is_not_promoted_by_a_pinned_proof(fixture):
    values = [o.model_dump(mode='json') for o in fixture[1]]
    values[0]['availability'][-1]['final'] = False
    observed = tuple(ObservedTicker.model_validate(v) for v in values)
    with pytest.raises(ValueError, match='Incomplete candle'):
        freeze((fixture[0], observed, fixture[2], fixture[3], fixture[4]))


def test_strict_replay_and_persisted_verification_are_deterministic(fixture, tmp_path):
    inputs = freeze(fixture)
    restored = VerifiedDailyInputs.model_validate_json(canonical_json(inputs))
    assert canonical_json(replay(inputs, fixture)) == canonical_json(replay(restored, fixture))
    trust = registry(fixture[0], fixture[2])
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        first = publish_verified_daily_signals(store, 'verified', inputs, expected_sha256=input_hash(inputs), trust=trust)
        assert publish_verified_daily_signals(store, 'verified', inputs, expected_sha256=input_hash(inputs), trust=trust) == first
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        assert load_verified_daily_signals(store, 'verified', expected_sha256=input_hash(inputs), trust=trust) == first
        with pytest.raises(ValueError):
            load_verified_daily_signals(store, 'verified', expected_sha256=input_hash(inputs))


def test_records_cannot_be_self_authorized_or_tampered(fixture):
    inputs = freeze(fixture)
    data = inputs.model_dump(mode='json')
    data['records'][0]['method'] = 'invented'
    with pytest.raises(ValueError):
        VerifiedDailyInputs.model_validate(data)
    data = inputs.model_dump(mode='json')
    data['records'][0]['evidence_id'] = 'tampered'
    with pytest.raises(ValueError, match='regenerated'):
        replay(VerifiedDailyInputs.model_validate(data), fixture)


def test_unverified_legacy_run_is_not_silently_upgraded(fixture, tmp_path):
    inputs = freeze(fixture)
    trust = registry(fixture[0], fixture[2])
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        store.publish('legacy', inputs.daily_inputs)
        with pytest.raises(ValueError, match='no strict verification'):
            load_verified_daily_signals(store, 'legacy', expected_sha256=input_hash(inputs), trust=trust)
        with pytest.raises(ValueError, match='verification metadata'):
            publish_verified_daily_signals(store, 'legacy', inputs, expected_sha256=input_hash(inputs), trust=trust)


class Provider:
    def __init__(self, observed, fail=False):
        self.observed = {o.snapshot.ticker: o for o in observed}
        self.fail = fail
        self.calls = []

    def fetch_daily(self, ticker, sessions):
        self.calls.append(ticker)
        if self.fail and ticker == 'MSFT':
            raise OSError('synthetic provider failure')
        return self.observed[ticker]


def test_untrusted_calendar_blocks_ingestion_before_any_provider_call(fixture, tmp_path):
    provider = Provider(fixture[1])
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        with pytest.raises(ValueError):
            ingest_verified_daily_signals(provider, fixture[0], fixture[2],
                policy=VerificationPolicy(publication_delay_seconds=600), verified_at=fixture[3],
                decision_at=fixture[4], store=store, run_id='blocked')
    assert provider.calls == []


@pytest.mark.parametrize('failure', ['provider', 'one_bad_ticker'])
def test_all_or_nothing_verified_publication(fixture, tmp_path, failure):
    changed = fixture
    if failure == 'one_bad_ticker':
        rows = [o.model_dump(mode='json') for o in fixture[1]]
        rows[2]['availability'][-1]['final'] = False
        changed = (fixture[0], tuple(ObservedTicker.model_validate(r) for r in rows), *fixture[2:])
    provider = Provider(changed[1], fail=failure == 'provider')
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        with pytest.raises((ValueError, RuntimeError)):
            ingest_verified_daily_signals(provider, changed[0], changed[2],
                policy=VerificationPolicy(publication_delay_seconds=600), verified_at=changed[3],
                decision_at=changed[4], store=store, run_id='blocked', trust=registry(changed[0], changed[2]))
    with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM run_verification').fetchone()[0] == 0


def test_atomic_verification_metadata_failure_rolls_back_run(fixture, tmp_path):
    inputs = freeze(fixture)
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
            db.execute("CREATE TRIGGER fail_proof BEFORE INSERT ON run_verification BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(sqlite3.IntegrityError):
            publish_verified_daily_signals(store, 'run', inputs, expected_sha256=input_hash(inputs),
                                          trust=registry(fixture[0], fixture[2]))
        with pytest.raises(KeyError):
            store.load('run', expected_sha256=input_hash(inputs.daily_inputs))
