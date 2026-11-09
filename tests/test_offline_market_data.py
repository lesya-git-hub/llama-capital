"""Only invented source responses; reuse 1C's explicitly synthetic calendar."""

from hashlib import sha256
import sqlite3

import pytest

from tests.test_market_verification import fixture, registry
from providers.offline_market_data import (
    OfflineDailyOHLCVProvider, OfflineProviderError, OfflineRateLimitError,
    SourceBatch, SourceObservation, SourceSnapshotStore, assemble_source_batch,
)
from tools.historical_snapshot import canonical_json, input_hash
from tools.market_verification import TrustRegistry, VerificationPolicy
from tools.verified_daily_pipeline import freeze_verified_daily_inputs


def batch(fixture):
    calendar, observed, evidence, _, _ = fixture
    mapping = {p.ticker: p.exchange for p in calendar.listings}
    return SourceBatch(calendar=calendar, evidence=evidence, observations=tuple(
        SourceObservation(dataset_id='synthetic-daily', dataset_version='fixture-1',
            exchange=mapping[o.snapshot.ticker], source_timestamp=None, retrieved_at=o.fetched_at,
            raw_payload=canonical_json(o.snapshot),
            raw_sha256=sha256(canonical_json(o.snapshot).encode()).hexdigest(), snapshot=o.snapshot)
        for o in observed))


def test_roundtrip_preserves_source_and_provisional_state(fixture, tmp_path):
    original = batch(fixture)
    store = SourceSnapshotStore(tmp_path / 'source.sqlite')
    digest = store.save(original)
    assert store.save(original) == digest
    restored = store.load(expected_sha256=digest)
    assert canonical_json(restored) == canonical_json(original)
    provider = OfflineDailyOHLCVProvider(restored)
    for o in restored.observations:
        observation = provider.fetch_daily(o.snapshot.ticker, restored.calendar.as_daily_schedule().sessions)
        assert observation.snapshot == o.snapshot
        assert observation.fetched_at == o.retrieved_at
        assert not any(a.final for a in observation.availability)
        assert o.source_timestamp is None
    assert TrustRegistry().pins == ()
    reversed_batch = original.model_copy(update={'observations': original.observations[::-1]})
    assert store.save(reversed_batch) == digest


@pytest.mark.parametrize('change', ['currency', 'duplicate', 'missing', 'adjustment', 'hash', 'future', 'exchange', 'identity'])
def test_bad_source_rejected(fixture, change):
    data = batch(fixture).model_dump(mode='json')
    row = data['observations'][0]
    if change == 'currency': row['snapshot']['currency'] = 'EUR'
    if change == 'duplicate': row['snapshot']['bars'].append(row['snapshot']['bars'][-1])
    if change == 'missing': row['snapshot']['bars'].pop()
    if change == 'adjustment': row['snapshot']['price_adjustment'] = 'dividend_adjusted'
    if change == 'hash': row['raw_sha256'] = '0' * 64
    if change == 'future': row['source_timestamp'] = '2099-01-01T00:00:00Z'
    if change == 'exchange': row['exchange'] = 'XNYS' if row['exchange'] == 'XNAS' else 'XNAS'
    if change == 'identity': row['dataset_id'] = 'conflicting'
    with pytest.raises(ValueError): SourceBatch.model_validate(data)


@pytest.mark.parametrize('error', [OSError('fixture failure'), OfflineRateLimitError('mock 429')])
def test_provider_failure_cannot_persist_partial_batch(fixture, tmp_path, error):
    frozen = batch(fixture)
    class Mock:
        def fetch_source(self, ticker, sessions):
            if ticker == 'MSFT': raise error
            return next(o for o in frozen.observations if o.snapshot.ticker == ticker)
    path = tmp_path / 'never-created.sqlite'
    store = SourceSnapshotStore(path)
    with pytest.raises(OfflineProviderError, match='MSFT') as caught:
        store.save(assemble_source_batch(Mock(), frozen.calendar))
    assert caught.value.__cause__ is error
    assert not path.exists()


def test_mock_normalization_and_exact_session_request(fixture):
    frozen = batch(fixture)
    class Mock:
        def fetch_source(self, ticker, sessions):
            return next(o for o in frozen.observations if o.snapshot.ticker == ticker)
    assembled = assemble_source_batch(Mock(), frozen.calendar, evidence=frozen.evidence)
    assert assembled == frozen
    provider = OfflineDailyOHLCVProvider(frozen)
    with pytest.raises(OfflineProviderError):
        provider.fetch_daily('AAPL', frozen.calendar.as_daily_schedule().sessions[:-1])


def test_pinned_evidence_never_promotes_offline_candles(fixture):
    frozen = batch(fixture)
    provider = OfflineDailyOHLCVProvider(frozen)
    observations = tuple(provider.fetch_daily(o.snapshot.ticker, frozen.calendar.as_daily_schedule().sessions)
                         for o in frozen.observations)
    settings = dict(policy=VerificationPolicy(publication_delay_seconds=600),
                    verified_at=fixture[3], decision_at=fixture[4])
    with pytest.raises(ValueError, match='Synthetic evidence'):
        freeze_verified_daily_inputs(frozen.calendar, observations, frozen.evidence, **settings)
    with pytest.raises(ValueError, match='Incomplete candle'):
        freeze_verified_daily_inputs(frozen.calendar, observations, frozen.evidence,
                                     trust=registry(frozen.calendar, frozen.evidence), **settings)
    assert frozen.evidence == fixture[2]  # Never generated or rewritten by ingestion.


def test_missing_evidence_stays_missing(fixture, tmp_path):
    frozen = batch(fixture).model_copy(update={'evidence': None})
    store = SourceSnapshotStore(tmp_path / 'source.sqlite')
    assert store.load(expected_sha256=store.save(frozen)).evidence is None


def test_archive_tampering_and_revisions(fixture, tmp_path):
    original = batch(fixture)
    store = SourceSnapshotStore(tmp_path / 'source.sqlite')
    digest = store.save(original)
    data = original.model_dump(mode='json')
    data['observations'][0]['dataset_version'] = 'revision-2'
    for o in data['observations']: o['dataset_version'] = 'revision-2'
    revised = SourceBatch.model_validate(data)
    revised_digest = store.save(revised)
    assert revised_digest != digest
    assert store.load(expected_sha256=digest) == original
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE source_batches SET content=? WHERE sha256=?', ('{}', digest))
    with pytest.raises(ValueError, match='integrity'):
        store.load(expected_sha256=digest)


def test_no_execution_imports():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('providers/offline_market_data.py').read_text())
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any('broker' in (m or '') or 'execution' in (m or '') for m in modules)
