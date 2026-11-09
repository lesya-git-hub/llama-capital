"""Invented offline interchange fixtures; no licensed vendor responses or calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3
from threading import Barrier

import pytest

from models.daily_signals import DAILY_UNIVERSE
from providers.provisional_market_data import (
    APP_ID, ObservationMetadata, RecordedResponse, ProvisionalArchive, ProvisionalBatch,
    ProvisionalDailyProvider, acquire_recorded_batch, normalize_recorded,
)
from tests.test_market_verification import fixture, registry
from tools.historical_snapshot import canonical_json, input_hash
from tools.market_verification import TrustRegistry, VerificationPolicy
from tools.verified_daily_pipeline import freeze_verified_daily_inputs


def responses(fixture):
    calendar, observations, _, _, _ = fixture
    exchanges = {r.ticker: r.exchange for r in calendar.listings}
    result = {}
    for observation in observations:
        snap = observation.snapshot
        raw = snap.model_dump(mode='json')
        del raw['source'], raw['calendar']
        raw.update(format='recorded_ohlcv_v1', provider_id=snap.source, dataset_id='invented-daily',
            dataset_version='fixture-1', feed='SYNTHETIC-CONSOLIDATED', exchange=exchanges[snap.ticker])
        body = json.dumps(raw, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        meta = ObservationMetadata(observation_id=snap.ticker + '-v1', fixture_kind='synthetic_test',
            licensing_reference='SYNTHETIC INVENTION; NO VENDOR LICENSE CLAIMED',
            provider_id=snap.source, dataset_id='invented-daily', dataset_version='fixture-1',
            feed='SYNTHETIC-CONSOLIDATED', ticker=snap.ticker, exchange=exchanges[snap.ticker],
            requested_dates=tuple(b.date for b in snap.bars), calendar_sha256=input_hash(calendar),
            acquired_start=observation.fetched_at - timedelta(seconds=1), acquired_end=observation.fetched_at,
            source_timestamp=None, response_id='fixture-' + snap.ticker, http_status=200,
            content_type='application/json', encoding='utf-8', page_count=1, pagination_complete=True,
            raw_sha256=sha256(body).hexdigest())
        result[snap.ticker] = RecordedResponse(meta, body)
    return result


class Fixtures:
    def __init__(self, values):
        self.values = values
        self.calls = []
    def read_recorded(self, ticker, sessions):
        self.calls.append(ticker)
        value = self.values[ticker]
        if isinstance(value, Exception):
            raise value
        return value


def changed(record, change):
    data = json.loads(record.body)
    change(data)
    body = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return RecordedResponse(record.metadata.model_copy(update={'raw_sha256': sha256(body).hexdigest()}), body)


def counts(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                     for table in ('observations', 'normalization', 'batches'))


def acquire(fixture, tmp_path, values=None, batch_id='batch1'):
    archive = ProvisionalArchive(tmp_path / 'provisional.sqlite')
    provider = Fixtures(values or responses(fixture))
    batch = acquire_recorded_batch(provider, archive, fixture[0], as_of=fixture[-1], batch_id=batch_id)
    return archive, batch


def test_roundtrip_exact_bytes_metadata_hashes_and_restart_replay(fixture, tmp_path):
    values = responses(fixture)
    archive, batch = acquire(fixture, tmp_path, values)
    assert batch.status == 'PROVISIONAL'
    assert counts(archive.path) == (6, 6, 1)
    assert input_hash(batch) == archive.save_batch(batch)
    again = ProvisionalArchive(archive.path).load_batch('batch1', expected_sha256=input_hash(batch))
    assert canonical_json(again) == canonical_json(batch)
    for observation in batch.observations:
        original = values[observation.metadata.ticker]
        assert archive.load(observation.metadata.observation_id) == original
        assert archive.record(original) == observation.observation_sha256
        assert observation.metadata.source_timestamp is None
        assert observation.candle_hashes == tuple(input_hash(b) for b in observation.snapshot.bars)
    assert counts(archive.path) == (6, 6, 1)


def test_provisional_never_published_even_with_pinned_proof_and_stable_hash(fixture, tmp_path):
    calendar, _, evidence, verified, decision = fixture
    archive, batch = acquire(fixture, tmp_path)
    provider = ProvisionalDailyProvider(archive, 'batch1', expected_sha256=input_hash(batch))
    sessions = calendar.as_daily_schedule().completed_sessions(decision)
    observed = tuple(provider.fetch_daily(t, sessions) for t in DAILY_UNIVERSE)
    assert all(not a.final for o in observed for a in o.availability)
    assert TrustRegistry().pins == ()
    with pytest.raises(ValueError, match='Incomplete candle'):
        freeze_verified_daily_inputs(calendar, observed, evidence,
            policy=VerificationPolicy(publication_delay_seconds=600), verified_at=verified,
            decision_at=decision, trust=registry(calendar, evidence))
    with pytest.raises(ValueError, match='real-world authority'):
        freeze_verified_daily_inputs(calendar, observed, evidence,
            policy=VerificationPolicy(publication_delay_seconds=600), verified_at=verified,
            decision_at=decision)
    assert archive.load_batch('batch1', expected_sha256=input_hash(batch)) == batch
    with pytest.raises(ValueError): provider.fetch_daily(DAILY_UNIVERSE[0], sessions[:-1])
    with pytest.raises(ValueError): provider.fetch_daily('NOT_IN_UNIVERSE', sessions)


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(currency='EUR'),
    lambda d: d.update(ticker='MSFT' if d['ticker'] != 'MSFT' else 'AAPL'),
    lambda d: d.update(exchange='XNYS' if d['exchange'] == 'XNAS' else 'XNAS'),
    lambda d: d.update(dataset_version='unexpected'),
    lambda d: d.update(price_adjustment='dividend_adjusted'),
    lambda d: d.update(volume_adjustment='unadjusted'),
    lambda d: d.update(feed='OTHER'),
    lambda d: d.update(format='vendor-live-unknown'),
    lambda d: d.update(extra='ambiguous'),
    lambda d: d['bars'].pop(),
    lambda d: d['bars'].append(d['bars'][-1]),
    lambda d: d['bars'].reverse(),
    lambda d: d['bars'][0].pop('dividend'),
    lambda d: d['bars'][0].pop('split_ratio'),
    lambda d: d['bars'][0].update(close=True),
    lambda d: d['bars'][0].update(close='100.0'),
    lambda d: d['bars'][0].update(high=1),
    lambda d: d['bars'][0].update(volume=-1),
    lambda d: d['bars'][0].update(split_ratio=0),
    lambda d: d['bars'][0].update(date='2020-01-01'),
    lambda d: d['bars'][0].update(date=d['bars'][0]['date'] + 'T00:00:00Z'),
])
def test_normalization_failures_retain_raw_and_never_complete_batch(fixture, tmp_path, mutation):
    values = responses(fixture)
    ticker = DAILY_UNIVERSE[2]
    values[ticker] = changed(values[ticker], mutation)
    archive = ProvisionalArchive(tmp_path / 'archive.sqlite')
    with pytest.raises(ValueError):
        acquire_recorded_batch(Fixtures(values), archive, fixture[0], as_of=fixture[-1], batch_id='incomplete')
    assert counts(archive.path) == (3, 3, 0)
    assert archive.load(ticker + '-v1').body == values[ticker].body
    with closing(sqlite3.connect(archive.path)) as db:
        failures = [json.loads(r[0]) for r in db.execute('SELECT content FROM normalization')]
    assert sum(row.get('status') == 'FAILED' for row in failures) == 1


@pytest.mark.parametrize('body', [b'not json', b'\xff\xfe\x00', b'{}', b'[]', b'{"x":1,"x":2}', b'{"x":NaN}', b''])
def test_exact_invalid_or_nonutf8_bytes_survive_normalization_failure(fixture, tmp_path, body):
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    value = RecordedResponse(original.metadata.model_copy(update={'raw_sha256': sha256(body).hexdigest()}), body)
    archive = ProvisionalArchive(tmp_path / 'raw.sqlite')
    archive.record(value)
    with pytest.raises((ValueError, UnicodeError)):
        archive.normalize(value.metadata.observation_id, fixture[0], as_of=fixture[-1])
    assert archive.load(value.metadata.observation_id).body == body
    assert counts(archive.path) == (1, 1, 0)


@pytest.mark.parametrize('updates', [
    {'http_status': 429, 'retry_after_seconds': 30}, {'http_status': 500}, {'http_status': 401},
    {'pagination_complete': False}, {'page_count': 2}, {'encoding': 'unknown'}, {'content_type': 'text/html'},
    {'calendar_sha256': '0' * 64},
])
def test_response_metadata_error_and_causality_fail_closed(fixture, tmp_path, updates):
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    value = replace(original, metadata=original.metadata.model_copy(update=updates))
    archive = ProvisionalArchive(tmp_path / 'meta.sqlite')
    archive.record(value)
    with pytest.raises(ValueError):
        archive.normalize(value.metadata.observation_id, fixture[0], as_of=fixture[-1])
    assert counts(archive.path) == (1, 1, 0)


def test_transport_failure_has_no_complete_batch_and_does_not_change_prior(fixture, tmp_path):
    archive, original = acquire(fixture, tmp_path)
    values = responses(fixture)
    values[DAILY_UNIVERSE[2]] = OSError('recorded fixture unavailable')
    provider = Fixtures(values)
    with pytest.raises(OSError):
        acquire_recorded_batch(provider, archive, fixture[0], as_of=fixture[-1], batch_id='failed')
    assert provider.calls == list(DAILY_UNIVERSE[:3])  # No implicit retries.
    assert archive.load_batch('batch1', expected_sha256=input_hash(original)) == original
    assert counts(archive.path) == (6, 6, 1)
    with pytest.raises(ValueError): archive.load_batch('failed', expected_sha256='0' * 64)


def test_revision_history_explicit_predecessor_and_unchanged_bytes_not_final(fixture, tmp_path):
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    archive = ProvisionalArchive(tmp_path / 'history.sqlite')
    archive.record(original)
    revised = changed(original, lambda d: d['bars'][-1].update(close=100.5))
    revised = replace(revised, metadata=revised.metadata.model_copy(update={
        'observation_id': 'revision2', 'previous_id': original.metadata.observation_id}))
    archive.record(revised)
    stable = replace(revised, metadata=revised.metadata.model_copy(update={'observation_id': 'revision3', 'previous_id': 'revision2'}))
    archive.record(stable)
    assert archive.load('revision3') == stable
    assert archive.load('revision2') == revised
    assert archive.load(original.metadata.observation_id) == original
    assert not any(x.final for x in archive.normalize('revision3', fixture[0], as_of=fixture[-1]).as_observed().availability)
    assert counts(archive.path) == (3, 1, 0)
    with pytest.raises(ValueError, match='predecessor'):
        archive.record(replace(stable, metadata=stable.metadata.model_copy(update={'observation_id': 'branch'})))
    with pytest.raises(ValueError, match='conflict'):
        archive.record(changed(original, lambda d: d['bars'][-1].update(close=100.5)))


def test_changed_overlapping_windows_are_durably_detected_and_replayed(fixture, tmp_path):
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    archive = ProvisionalArchive(tmp_path / 'overlap.sqlite')
    archive.record(original)
    first = archive.normalize(original.metadata.observation_id, fixture[0], as_of=fixture[-1])
    revised = changed(original, lambda d: (d['bars'].pop(0), d['bars'][-1].update(close=100.5)))
    calendar = fixture[0].model_copy(update={'coverage_start': original.metadata.requested_dates[1],
        'sessions': tuple(s for s in fixture[0].sessions if s.date >= original.metadata.requested_dates[1]),
        'closed_dates': tuple(s for s in fixture[0].closed_dates if s.date >= original.metadata.requested_dates[1])})
    revised = replace(revised, metadata=revised.metadata.model_copy(update={'observation_id': 'overlap',
        'requested_dates': original.metadata.requested_dates[1:], 'calendar_sha256': input_hash(calendar)}))
    archive.record(revised)
    current = archive.normalize('overlap', calendar, as_of=fixture[-1])
    evidence = archive.conflicts('overlap')
    assert len(evidence) == 1
    assert evidence[0]['previous_id'] == original.metadata.observation_id
    assert evidence[0]['changed_dates'] == [original.metadata.requested_dates[-1].isoformat()]
    assert archive.normalize('overlap', calendar, as_of=fixture[-1]) == current
    assert archive.conflicts('overlap') == evidence
    assert archive.normalize(original.metadata.observation_id, fixture[0], as_of=fixture[-1]) == first
    with closing(sqlite3.connect(archive.path)) as db:
        db.execute("UPDATE conflicts SET sha256='broken'")
        db.commit()
    with pytest.raises(ValueError, match='integrity'):
        archive.conflicts('overlap')


def test_raw_decimal_spellings_preserved_with_deterministic_normalized_hashes(fixture):
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    changed_body = original.body.replace(b'100.0', b'1e2')
    assert changed_body != original.body
    modified = RecordedResponse(original.metadata.model_copy(update={'raw_sha256': sha256(changed_body).hexdigest()}), changed_body)
    first = normalize_recorded(original, fixture[0], as_of=fixture[-1])
    second = normalize_recorded(modified, fixture[0], as_of=fixture[-1])
    assert first.snapshot == second.snapshot and first.candle_hashes == second.candle_hashes
    assert first.observation_sha256 != second.observation_sha256


def test_missing_normalization_and_prior_revision_evidence_fail_closed(fixture, tmp_path):
    archive, batch = acquire(fixture, tmp_path)
    original = archive.load(DAILY_UNIVERSE[0] + '-v1')
    new = replace(original, metadata=original.metadata.model_copy(update={'observation_id': 'rev2',
        'previous_id': original.metadata.observation_id}))
    archive.record(new)
    with closing(sqlite3.connect(archive.path)) as db:
        db.execute('DELETE FROM observations WHERE observation_id=?', (original.metadata.observation_id,))
        db.commit()
    with pytest.raises(ValueError, match='Missing observation'):
        archive.load('rev2')
    with pytest.raises(ValueError): archive.load_batch('batch1', expected_sha256=input_hash(batch))


def test_schema_context_and_normalizer_changes_refuse_historical_replay(fixture, tmp_path, monkeypatch):
    import providers.provisional_market_data as module
    archive, batch = acquire(fixture, tmp_path)
    monkeypatch.setattr(module, 'normalizer_hash', lambda: '0' * 64)
    with pytest.raises(ValueError, match='replay differs'):
        archive.load_batch('batch1', expected_sha256=input_hash(batch))


@pytest.mark.parametrize('updates', [
    {'status': 'VERIFIED'}, {'licensing_reference': ' '}, {'acquired_end': 123},
    {'acquired_end': '2020-11-10T21:10:00'}, {'source_timestamp': '2030-01-01T00:00:00Z'},
    {'requested_dates': ['2020-01-01T00:00:00Z']},
])
def test_ambiguous_or_verified_metadata_rejected(fixture, updates):
    meta = responses(fixture)[DAILY_UNIVERSE[0]].metadata.model_dump(mode='json')
    with pytest.raises(ValueError): ObservationMetadata.model_validate(meta | updates)


def test_future_acquisition_and_unfinished_context_fail_closed(fixture, tmp_path):
    record = responses(fixture)[DAILY_UNIVERSE[0]]
    meta = record.metadata.model_copy(update={'acquired_end': fixture[-1] + timedelta(seconds=1)})
    archive = ProvisionalArchive(tmp_path / 'future.sqlite')
    archive.record(replace(record, metadata=meta))
    with pytest.raises(ValueError): archive.normalize(meta.observation_id, fixture[0], as_of=fixture[-1])
    provider = Fixtures(responses(fixture))
    with pytest.raises(ValueError):
        acquire_recorded_batch(provider, archive, fixture[0], as_of=fixture[0].available_at, batch_id='no-sessions')
    assert provider.calls == []


@pytest.mark.parametrize('table,column', [('observations','body'), ('observations','metadata_json'), ('normalization','content'), ('batches','content')])
def test_archive_tampering_fails_replay(fixture, tmp_path, table, column):
    archive, batch = acquire(fixture, tmp_path)
    with closing(sqlite3.connect(archive.path)) as db:
        value = b'tampered' if column == 'body' else 'tampered'
        db.execute(f'UPDATE {table} SET {column}=?', (value,))
        db.commit()
    with pytest.raises((ValueError, TypeError)):
        archive.load_batch('batch1', expected_sha256=input_hash(batch))


def test_partial_constructed_batch_and_batch_identity_conflicts_refused(fixture, tmp_path):
    archive, batch = acquire(fixture, tmp_path)
    with pytest.raises(ValueError): archive.save_batch(batch.model_copy(update={'observations': batch.observations[:-1]}))
    with pytest.raises(ValueError): archive.save_batch(batch.model_copy(update={'observations': tuple(reversed(batch.observations))}))
    changed_context = batch.model_copy(update={'as_of': batch.as_of + timedelta(seconds=1)})
    with pytest.raises(ValueError): archive.save_batch(changed_context)
    assert counts(archive.path)[-1] == 1


def test_failure_in_complete_batch_insert_leaves_raw_but_no_success(fixture, tmp_path):
    archive = ProvisionalArchive(tmp_path / 'fault.sqlite')
    with closing(sqlite3.connect(archive.path)) as db:
        db.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'injected batch write failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        acquire_recorded_batch(Fixtures(responses(fixture)), archive, fixture[0], as_of=fixture[-1], batch_id='not-complete')
    assert counts(archive.path) == (6, 6, 0)


def test_missing_or_incompatible_archive_never_repaired(fixture, tmp_path):
    path = tmp_path / 'archive.sqlite'
    archive = ProvisionalArchive(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP TABLE normalization')
    with pytest.raises(sqlite3.Error): ProvisionalArchive(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError): archive.load('missing')
    path.unlink()
    with pytest.raises(sqlite3.Error): archive.load('missing')
    assert not path.exists()


def test_unrelated_database_left_unchanged(tmp_path):
    path = tmp_path / 'other.sqlite'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE precious (value TEXT)')
        db.execute("INSERT INTO precious VALUES ('keep')")
        db.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError): ProvisionalArchive(path)
    assert path.read_bytes() == before


def test_concurrent_identical_record_is_idempotent(fixture, tmp_path):
    path = tmp_path / 'race.sqlite'
    ProvisionalArchive(path)
    response = responses(fixture)[DAILY_UNIVERSE[0]]
    barrier = Barrier(2)
    def write(_):
        archive = ProvisionalArchive(path)
        barrier.wait(timeout=10)
        return archive.record(response)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(write, range(2)))
    assert result[0] == result[1] and counts(path) == (1, 0, 0)


def test_concurrent_revision_writers_cannot_fork_a_request_history(fixture, tmp_path):
    path = tmp_path / 'revisions.sqlite'
    archive = ProvisionalArchive(path)
    original = responses(fixture)[DAILY_UNIVERSE[0]]
    archive.record(original)
    barrier = Barrier(2)
    def write(identity):
        value = replace(original, metadata=original.metadata.model_copy(update={
            'observation_id': identity, 'previous_id': original.metadata.observation_id}))
        writer = ProvisionalArchive(path)
        barrier.wait(timeout=10)
        try:
            writer.record(value)
            return 'recorded'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ['r1', 'r2'])) == ['conflict', 'recorded']
    assert counts(path) == (2, 0, 0)


def test_normalization_write_failure_does_not_lose_raw_or_complete_batch(fixture, tmp_path):
    archive = ProvisionalArchive(tmp_path / 'norm-fault.sqlite')
    with closing(sqlite3.connect(archive.path)) as db:
        db.execute("CREATE TRIGGER fail_norm BEFORE INSERT ON normalization BEGIN SELECT RAISE(ABORT,'injected normalization write failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        acquire_recorded_batch(Fixtures(responses(fixture)), archive, fixture[0], as_of=fixture[-1], batch_id='no-result')
    assert counts(archive.path) == (1, 0, 0)


def test_provisional_ingestion_cannot_publish_any_verified_run(fixture, tmp_path):
    from tools.daily_signal_pipeline import DailySignalStore
    from tools.verified_daily_pipeline import ingest_verified_daily_signals
    archive, batch = acquire(fixture, tmp_path)
    provider = ProvisionalDailyProvider(archive, 'batch1', expected_sha256=input_hash(batch))
    calendar, _, evidence, verified, decision = fixture
    with DailySignalStore(tmp_path / 'signals.sqlite') as store:
        with pytest.raises(ValueError, match='Incomplete candle'):
            ingest_verified_daily_signals(provider, calendar, evidence, policy=VerificationPolicy(publication_delay_seconds=600),
                verified_at=verified, decision_at=decision, store=store, run_id='forbidden', trust=registry(calendar, evidence))
        assert store._db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0
        assert store._db.execute('SELECT COUNT(*) FROM run_verification').fetchone()[0] == 0
    assert TrustRegistry().pins == ()


def test_replay_has_no_transport_or_execution_dependencies(fixture, tmp_path, monkeypatch):
    import socket
    import providers.provisional_market_data as module
    def forbidden(*args, **kwargs): raise AssertionError('No external request permitted')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    archive, batch = acquire(fixture, tmp_path)
    assert archive.load_batch('batch1', expected_sha256=input_hash(batch)) == batch
    source = open(module.__file__, encoding='utf-8').read()
    for name in ('import requests', 'import http', 'paper_broker', 'gated_execution', 'fx_conversion'):
        assert name not in source
