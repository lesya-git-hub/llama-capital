"""Stage A: invented evidence only, no provider downloads or order execution."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3

import pytest

from models.calendar_finality_evidence import (SourceReceipt, EvidenceRef, CalendarSnapshot,
    ExceptionalNotice, NoticeCoverage, ProviderClaim, ClaimDocument, EvidenceManifest,
    EligibilityRequest, ReviewDisposition, EligibilityResult)
from tools.calendar_finality_store import EvidenceStore, SourceRecord
from tools.calendar_finality_compiler import compile_calendar
from tools.calendar_finality_review import evaluate_candidate, replay_candidate
from tools.historical_snapshot import canonical_json, input_hash
from tools.market_verification import NEW_YORK, TrustRegistry
from tools.verified_daily_pipeline import VerifiedDailyInputs
from tests.test_market_verification import fixture
from tests.test_provisional_market_data import acquire, responses, changed


def record(store, identity, kind, value, *, source, version='fixture-1', at,
           scope='synthetic_test', previous=None, key=None):
    body = canonical_json(value).encode() if hasattr(value, 'model_dump') else value
    receipt = SourceReceipt(receipt_id=identity, kind=kind, scope=scope, source=source, version=version,
        logical_key=key or identity, previous_id=previous, published_at=at, acquired_start=at, acquired_end=at,
        clock_id='SYNTHETIC-INDEPENDENT-CLOCK', uncertainty_ms=0,
        provenance='INVENTED TEST EVIDENCE; NOT EXCHANGE OR VENDOR AUTHORITY',
        licensing_reference='SYNTHETIC ONLY; NO DATA LICENSE CLAIM', body_sha256=sha256(body).hexdigest())
    digest = store.record_source(SourceRecord(receipt, body))
    return EvidenceRef(receipt_id=identity, sha256=digest)


def setup(fixture, tmp_path, *, mutate_claims=None, skip_notice=False, no_claims=False):
    archive, batch = acquire(fixture, tmp_path)
    calendar, _, old_evidence, verified, decision = fixture
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    cal_ref = record(store, 'calendar1', 'calendar', CalendarSnapshot(calendar=calendar, listing_history_confirmed=True),
        source=calendar.source, version=calendar.version, at=calendar.available_at)
    notices = []
    for index, row in enumerate(calendar.closed_dates):
        if row.reason == 'exceptional_closure':
            notices.append(record(store, f'closed-{index}', 'notice',
                ExceptionalNotice(exchange=row.exchange, session_date=row.date.isoformat(), action='exceptional_closure', closes_at=None),
                source='SYNTHETIC-OFFICIAL-NOTICE', at=calendar.available_at))
    for index, row in enumerate(calendar.sessions):
        if row.closes_at.astimezone(NEW_YORK).hour < 16:
            notices.append(record(store, f'early-{index}', 'notice',
                ExceptionalNotice(exchange=row.exchange, session_date=row.date.isoformat(), action='early_close', closes_at=row.closes_at),
                source='SYNTHETIC-OFFICIAL-NOTICE', at=calendar.available_at))
    coverage = record(store, 'coverage1', 'coverage', NoticeCoverage(calendar_sha256=input_hash(calendar), through=verified, complete=True),
        source='SYNTHETIC-NOTICE-CHANNEL', at=verified)
    proofs = {(p.ticker, p.date): p for p in old_evidence.candles}
    claims = []
    for observation in batch.observations:
        for bar in observation.snapshot.bars:
            meta = observation.metadata
            claims.append(ProviderClaim(observation_id=meta.observation_id, observation_sha256=observation.observation_sha256,
                raw_sha256=meta.raw_sha256, normalizer_sha256=observation.normalizer_sha256, dataset_id=meta.dataset_id,
                dataset_version=meta.dataset_version, feed=meta.feed, release_id='SYNTHETIC-RELEASE:' + meta.observation_id,
                completion_policy_reference='SYNTHETIC COMPLETED RELEASE POLICY', adjustment_policy_reference='SYNTHETIC SPLIT BASIS',
                proof=proofs[(meta.ticker, bar.date)]))
    if mutate_claims:
        claims = mutate_claims(claims)
    claim_ref = record(store, 'claims1', 'provider_claim', ClaimDocument(claims=tuple(claims)),
        source=old_evidence.source, at=max(p.issued_at for p in old_evidence.candles))
    manifest = EvidenceManifest(manifest_id='manifest1', calendar=cal_ref, notices=tuple(notices[:-1] if skip_notice else notices),
        coverage=coverage, provider_claims=() if no_claims else (claim_ref,))
    request = EligibilityRequest(request_id='evaluation1', batch_id=batch.batch_id, batch_sha256=input_hash(batch),
        manifest_sha256=input_hash(manifest), verified_at=verified, decision_at=decision, publication_delay_seconds=600)
    review = ReviewDisposition(review_id='review1', request_sha256=input_hash(request), corpus_sha256=store.snapshot()[1],
        operator_id='synthetic-reviewer', authorization_id='synthetic-independent-approval', reason='Explicit synthetic evaluation only',
        reviewed_at=verified, approved=True)
    review_hash = store.record_review(review, authorize=lambda r: True)
    return archive, store, batch, manifest, request, review, review_hash


def evaluate(values, **overrides):
    archive, store, batch, manifest, request, review, digest = values
    return evaluate_candidate(archive, store, request, manifest,
        **(dict(review_id=review.review_id, review_sha256=digest) | overrides))


def test_positive_synthetic_projection_preserves_raw_provisional_and_replays(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    archive, store, batch, manifest, request, review, digest = values
    before = archive.path.read_bytes()
    result = evaluate(values)
    assert result.status == 'ELIGIBLE_FOR_1C_PROJECTION'
    assert result.calendar_valid and result.finality_valid and not result.reasons
    projected = VerifiedDailyInputs.model_validate_json(result.synthetic_projection_json)
    assert projected.scope == 'synthetic_test'
    assert all(a.final for o in projected.daily_inputs.observed for a in o.availability)
    assert all(not a.final for o in batch.observations for a in o.as_observed().availability)
    assert archive.path.read_bytes() == before and TrustRegistry().pins == ()
    assert replay_candidate(archive, store, request_id=request.request_id, expected_sha256=input_hash(result), review_id=review.review_id) == result
    assert store.load_evaluation(request.request_id, input_hash(result)) == result


def test_calendar_can_pass_while_no_finality_claims_fail(fixture, tmp_path):
    result = evaluate(setup(fixture, tmp_path, no_claims=True))
    assert result.calendar_valid and not result.finality_valid
    assert result.status == 'HELD_FOR_REVIEW' and result.synthetic_projection_json is None


def test_provider_claims_do_not_substitute_for_missing_calendar_notice(fixture, tmp_path):
    result = evaluate(setup(fixture, tmp_path, skip_notice=True))
    assert not result.calendar_valid and result.finality_valid
    assert result.status == 'HELD_FOR_REVIEW'


@pytest.mark.parametrize('mutation', [
    lambda c: c[:-1],
    lambda c: c + [c[0]],
    lambda c: [v for v in c if v.proof.ticker != 'MSFT'],
    lambda c: [c[0].model_copy(update={'raw_sha256': '0' * 64}), *c[1:]],
    lambda c: [c[0].model_copy(update={'feed': 'WRONG'}), *c[1:]],
    lambda c: [c[0].model_copy(update={'proof': c[0].proof.model_copy(update={'provider_final': False})}), *c[1:]],
    lambda c: [c[0].model_copy(update={'proof': c[0].proof.model_copy(update={'completed_session': False})}), *c[1:]],
    lambda c: [c[0].model_copy(update={'proof': c[0].proof.model_copy(update={'candle_sha256': '0' * 64})}), *c[1:]],
    lambda c: [c[0].model_copy(update={'proof': c[0].proof.model_copy(update={'issued_at': c[0].proof.official_close - timedelta(seconds=1)})}), *c[1:]],
])
def test_incomplete_wrong_or_unattested_claims_fail_closed(fixture, tmp_path, mutation):
    result = evaluate(setup(fixture, tmp_path, mutate_claims=mutation))
    assert result.calendar_valid and not result.finality_valid
    assert result.status == 'HELD_FOR_REVIEW' and result.synthetic_projection_json is None


@pytest.mark.parametrize('alteration', ['late_receipt', 'uncertain_receipt', 'missing_publication', 'real_source', 'malformed'])
def test_receipt_causality_and_scope_not_replaced_by_elapsed_time(fixture, tmp_path, alteration):
    values = setup(fixture, tmp_path)
    archive, store, batch, manifest, request, review, digest = values
    record1 = store.snapshot()[0]['claims1']
    updates = dict(receipt_id='claims2', previous_id='claims1')
    if alteration == 'late_receipt': updates['acquired_end'] = request.verified_at
    if alteration == 'uncertain_receipt': updates['uncertainty_ms'] = 60 * 60 * 1000
    if alteration == 'missing_publication': updates['published_at'] = None
    if alteration == 'real_source': updates.update(scope='real', previous_id=None)
    body = b'{bad' if alteration == 'malformed' else record1.body
    updates['body_sha256'] = sha256(body).hexdigest()
    receipt = record1.receipt.model_copy(update=updates)
    new_hash = store.record_source(SourceRecord(receipt, body))
    new_manifest = manifest.model_copy(update={'provider_claims': (EvidenceRef(receipt_id='claims2', sha256=new_hash),)})
    new_request = request.model_copy(update={'manifest_sha256': input_hash(new_manifest)})
    result = evaluate_candidate(archive, store, new_request, new_manifest, review_id=review.review_id, review_sha256=digest)
    assert not result.finality_valid and result.status == 'HELD_FOR_REVIEW'


@pytest.mark.parametrize('authorization', [None, lambda r: False, lambda r: 1])
def test_independent_review_authorization_required(fixture, tmp_path, authorization):
    values = setup(fixture, tmp_path)
    review = values[-2].model_copy(update={'review_id': 'unauthorized'})
    with pytest.raises(PermissionError): values[1].record_review(review, authorize=authorization)
    result = evaluate(values, review_id='unauthorized', review_sha256='0' * 64)
    assert result.status == 'HELD_FOR_REVIEW' and result.synthetic_projection_json is None


def test_real_requests_cannot_create_final_projection_or_real_trust(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    archive, store, batch, manifest, request, review, digest = values
    request = request.model_copy(update={'scope': 'real'})
    result = evaluate_candidate(archive, store, request, manifest)
    assert result.status == 'PROVISIONAL' and result.synthetic_projection_json is None
    assert not result.calendar_valid and not result.finality_valid
    with pytest.raises(PermissionError): store.record_review(review.model_copy(update={'scope': 'real'}), authorize=lambda r: True)
    with pytest.raises(ValueError): EligibilityResult.model_validate(result.model_dump(mode='json') | {'status': 'ELIGIBLE_FOR_1C_PROJECTION'})
    assert TrustRegistry().pins == ()


def test_reverse_archive_conflict_prevents_old_candidate_eligibility(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    archive, store, batch, manifest, request, review, digest = values
    original = responses(fixture)['AAPL']
    revision = changed(original, lambda d: d['bars'][-1].update(close=100.5))
    revision = replace(revision, metadata=revision.metadata.model_copy(update={'observation_id': 'aapl-new', 'previous_id': 'AAPL-v1'}))
    archive.record(revision)
    archive.normalize('aapl-new', fixture[0], as_of=fixture[-1])
    assert archive.conflicts('AAPL-v1') == ()  # Reverse edge must still block.
    result = evaluate(values)
    assert result.status == 'HELD_FOR_REVIEW'
    assert 'UNRESOLVED_ARCHIVE_REVISION_CONFLICT' in result.reasons


def test_later_evidence_revision_preserves_old_receipt_but_requires_new_review(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    archive, store, batch, manifest, request, review, digest = values
    old = evaluate(values)
    source = store.snapshot()[0]['claims1']
    new = replace(source, receipt=source.receipt.model_copy(update={'receipt_id': 'claims2', 'previous_id': 'claims1'}))
    store.record_source(new)  # Stable body still does not refresh old approval.
    assert 'claims1' in store.snapshot()[0]
    with pytest.raises(ValueError, match='history changed'):
        replay_candidate(archive, store, request_id=request.request_id, expected_sha256=input_hash(old), review_id=review.review_id)
    request2 = request.model_copy(update={'request_id': 'new-evaluation'})
    held = evaluate_candidate(archive, store, request2, manifest, review_id=review.review_id, review_sha256=digest)
    assert not held.finality_valid and held.status == 'HELD_FOR_REVIEW'


def test_calendar_replay_has_early_close_dst_and_exceptional_closures(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    records, _ = values[1].snapshot()
    calendar = compile_calendar(records, values[3], at=values[4].verified_at)
    assert calendar == fixture[0]
    local = {s.closes_at.astimezone(NEW_YORK).hour for s in calendar.sessions}
    assert local == {13, 16}
    assert {s.closes_at.hour for s in calendar.sessions if s.closes_at.astimezone(NEW_YORK).hour == 16} == {20, 21}
    assert any(r.reason == 'exceptional_closure' for r in calendar.closed_dates)


@pytest.mark.parametrize('alteration', ['stale', 'incomplete', 'wrong_calendar'])
def test_notice_coverage_failures_independent_of_finality(fixture, tmp_path, alteration):
    values = setup(fixture, tmp_path)
    store, manifest, request = values[1], values[3], values[4]
    coverage = NoticeCoverage(calendar_sha256=input_hash(fixture[0]), through=request.verified_at, complete=True)
    updates = {'through': request.verified_at - timedelta(seconds=1)} if alteration == 'stale' else (
        {'complete': False} if alteration == 'incomplete' else {'calendar_sha256': '0' * 64})
    ref = record(store, 'coverage2', 'coverage', coverage.model_copy(update=updates), source='SYNTHETIC-NOTICE-CHANNEL',
        at=request.verified_at, key='coverage1', previous='coverage1')
    new_manifest = manifest.model_copy(update={'coverage': ref})
    result = evaluate_candidate(values[0], store, request.model_copy(update={'manifest_sha256': input_hash(new_manifest)}), new_manifest)
    assert not result.calendar_valid and result.finality_valid
    assert result.status == 'HELD_FOR_REVIEW'


def test_omitted_competing_exception_notice_cannot_be_ignored(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    row = next(s for s in fixture[0].sessions if s.closes_at.astimezone(NEW_YORK).hour == 16)
    record(values[1], 'competing', 'notice', ExceptionalNotice(exchange=row.exchange,
        session_date=row.date.isoformat(), action='exceptional_closure', closes_at=None),
        source='SYNTHETIC-SECOND-NOTICE', at=fixture[0].available_at)
    result = evaluate(values)
    assert not result.calendar_valid and 'competing' in ' '.join(result.reasons)


def test_manifest_cannot_hide_conflicting_overlapping_calendar_snapshot(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    calendar = fixture[0]
    rows = list(calendar.sessions)
    rows[-1] = rows[-1].model_copy(update={'closes_at': rows[-1].closes_at + timedelta(minutes=1)})
    alternative = calendar.model_copy(update={'sessions': tuple(rows)})
    record(values[1], 'competing-calendar', 'calendar',
        CalendarSnapshot(calendar=alternative, listing_history_confirmed=True),
        source=calendar.source, version=calendar.version, at=calendar.available_at)
    result = evaluate(values)
    assert not result.calendar_valid and result.status == 'HELD_FOR_REVIEW'
    assert 'Conflicting overlapping calendar' in ' '.join(result.reasons)


def test_real_1m_batch_is_isolated_even_when_request_claims_synthetic(fixture, tmp_path):
    from tests.test_provisional_market_data import Fixtures
    from providers.provisional_market_data import ProvisionalArchive, acquire_recorded_batch
    calendar = fixture[0].model_copy(update={'scope': 'real'})
    records = responses(fixture)
    for ticker, response in tuple(records.items()):
        records[ticker] = replace(response, metadata=response.metadata.model_copy(update={
            'fixture_kind': 'licensed_offline', 'calendar_sha256': input_hash(calendar),
            'licensing_reference': 'ADVERSARIAL SYNTHETIC CLAIM; NOT ACTUAL LICENSED DATA'}))
    archive = ProvisionalArchive(tmp_path / 'declared-real.sqlite')
    batch = acquire_recorded_batch(Fixtures(records), archive, calendar, as_of=fixture[-1], batch_id='real-label')
    values = setup(fixture, tmp_path)
    request = values[4].model_copy(update={'batch_id': batch.batch_id, 'batch_sha256': input_hash(batch)})
    result = evaluate_candidate(archive, values[1], request, values[3])
    assert result.scope == 'real' and result.status == 'PROVISIONAL'
    assert result.synthetic_projection_json is None and not result.finality_valid
    assert TrustRegistry().pins == ()
    from tools.calendar_finality_compiler import compile_provider_evidence
    with pytest.raises(ValueError, match='synthetic compiler only'):
        compile_provider_evidence({}, values[3], batch, at=request.verified_at)
    with pytest.raises(ValueError, match='Only synthetic projection'):
        EligibilityResult.model_validate(result.model_dump(mode='json') | dict(scope='synthetic_test',
            status='ELIGIBLE_FOR_1C_PROJECTION', calendar_valid=True, finality_valid=True, reasons=(),
            synthetic_projection_json='{"scope":"real"}'))


def test_evidence_changed_before_result_commit_fails_without_success(fixture, tmp_path, monkeypatch):
    values = setup(fixture, tmp_path)
    store = values[1]
    original = store.save_evaluation
    def race(result):
        raw = store.snapshot()[0]['claims1']
        store.record_source(replace(raw, receipt=raw.receipt.model_copy(update={'receipt_id': 'racing-revision', 'previous_id': 'claims1'})))
        return original(result)
    monkeypatch.setattr(store, 'save_evaluation', race)
    with pytest.raises(ValueError, match='changed before durable'):
        evaluate(values)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0] == 0


def test_review_generation_is_checked_inside_its_write_transaction(fixture, tmp_path, monkeypatch):
    values = setup(fixture, tmp_path)
    store = values[1]
    original = store._immutable
    def race(*args, **kwargs):
        raw = store.snapshot()[0]['claims1']
        store.record_source(replace(raw, receipt=raw.receipt.model_copy(update={'receipt_id': 'racing-review', 'previous_id': 'claims1'})))
        return original(*args, **kwargs)
    monkeypatch.setattr(store, '_immutable', race)
    review = values[-2].model_copy(update={'review_id': 'review-race'})
    with pytest.raises(ValueError, match='changed before durable'):
        store.record_review(review, authorize=lambda r: True)


def test_missing_review_and_denied_review_never_produce_projection(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    assert evaluate(values, review_id=None, review_sha256=None).status == 'HELD_FOR_REVIEW'
    request = values[4].model_copy(update={'request_id': 'denied-evaluation'})
    review = values[-2].model_copy(update={'review_id': 'denied', 'approved': False, 'request_sha256': input_hash(request)})
    digest = values[1].record_review(review, authorize=lambda r: True)
    result = evaluate_candidate(values[0], values[1], request, values[3], review_id='denied', review_sha256=digest)
    assert result.status == 'HELD_FOR_REVIEW' and result.synthetic_projection_json is None


def test_competing_review_cannot_be_hidden_by_selecting_an_approval(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    denied = values[-2].model_copy(update={'review_id': 'competing-denial', 'approved': False})
    values[1].record_review(denied, authorize=lambda r: True)
    result = evaluate(values)
    assert result.status == 'HELD_FOR_REVIEW' and result.synthetic_projection_json is None
    assert 'Conflicting review' in ' '.join(result.reasons)


def test_competing_review_before_result_commit_prevents_eligible_return(fixture, tmp_path, monkeypatch):
    values = setup(fixture, tmp_path)
    store = values[1]
    original = store.save_evaluation
    def race(result):
        denied = values[-2].model_copy(update={'review_id': 'racing-denial', 'approved': False})
        store.record_review(denied, authorize=lambda r: True)
        return original(result)
    monkeypatch.setattr(store, 'save_evaluation', race)
    with pytest.raises(ValueError, match='Conflicting review'):
        evaluate(values)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0] == 0


def test_replay_retains_review_identity_and_refuses_engine_change(fixture, tmp_path, monkeypatch):
    import tools.calendar_finality_review as module
    values = setup(fixture, tmp_path)
    result = evaluate(values)
    assert replay_candidate(values[0], values[1], request_id=result.request.request_id, expected_sha256=input_hash(result)) == result
    monkeypatch.setattr(module, 'engine_hash', lambda: '0' * 64)
    with pytest.raises(ValueError, match='implementation changed'):
        replay_candidate(values[0], values[1], request_id=result.request.request_id, expected_sha256=input_hash(result))


def test_incompatible_or_missing_evidence_schema_is_not_repaired(tmp_path):
    path = tmp_path / 'schema.sqlite'
    store = EvidenceStore(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP TABLE reviews')
    with pytest.raises(sqlite3.Error): EvidenceStore(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError): store.snapshot()
    path.unlink()
    with pytest.raises(sqlite3.Error): store.snapshot()
    assert not path.exists()


@pytest.mark.parametrize('table,column', [('sources','body'), ('sources','content'), ('reviews','content'), ('evaluations','content')])
def test_tampered_or_missing_evidence_never_replays(fixture, tmp_path, table, column):
    values = setup(fixture, tmp_path)
    result = evaluate(values)
    with closing(sqlite3.connect(values[1].path)) as db:
        db.execute(f'UPDATE {table} SET {column}=?', (b'bad' if column == 'body' else 'bad',))
        db.commit()
    with pytest.raises((ValueError, TypeError)):
        replay_candidate(values[0], values[1], request_id=result.request.request_id, expected_sha256=input_hash(result), review_id=values[-2].review_id)


def test_evaluation_audit_failure_never_returns_eligible_result(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    with closing(sqlite3.connect(values[1].path)) as db:
        db.execute("CREATE TRIGGER fail_eval BEFORE INSERT ON evaluations BEGIN SELECT RAISE(ABORT,'injected evaluation audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError): evaluate(values)
    with closing(sqlite3.connect(values[1].path)) as db:
        assert db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0] == 0


def test_source_revision_fork_and_immutable_ids_refused(fixture, tmp_path):
    values = setup(fixture, tmp_path)
    store = values[1]
    source = store.snapshot()[0]['calendar1']
    assert store.record_source(source) == values[3].calendar.sha256
    bad = replace(source, receipt=source.receipt.model_copy(update={'provenance': 'changed'}))
    with pytest.raises(ValueError, match='conflict'): store.record_source(bad)
    bad = replace(source, receipt=source.receipt.model_copy(update={'receipt_id': 'fork'}))
    with pytest.raises(ValueError, match='predecessor'): store.record_source(bad)


def test_malformed_sources_can_be_archived_but_cannot_compile(tmp_path):
    store = EvidenceStore(tmp_path / 'raw.sqlite')
    from datetime import datetime, timezone
    ref = record(store, 'bad', 'calendar', b'\xff\x00', source='fixture', at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert store.snapshot()[0]['bad'].body == b'\xff\x00'


def test_no_network_or_execution_and_default_registry_unchanged(fixture, tmp_path, monkeypatch):
    import socket
    def forbidden(*args, **kwargs): raise AssertionError('No external calls')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    assert evaluate(setup(fixture, tmp_path)).scope == 'synthetic_test'
    assert TrustRegistry().pins == ()
