"""Offline coordinator tests. All evidence, principals and stores are invented."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import base64
import sqlite3
from threading import Barrier, Event
import subprocess
import sys

import pytest

from models.evidence_admission import Principal, ReviewRequest, SourceVersion
from tests.test_market_verification import fixture
from tests.test_calendar_finality_evidence import setup, evaluate
from tools.evidence_admission_coordinator import (EvidenceAdmissionCoordinator, AdmissionRejected,
    prepare_from_stage_a, validate_bundle)
from tools.historical_snapshot import input_hash
from tools.market_verification import TrustRegistry
from tools.synthetic_evidence_participant import SyntheticEvidenceParticipant

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
ROLES = {'prep': ('preparer', 'reviewer', 'admitter'), 'reviewer': ('reviewer', 'admitter'),
    'admitter': ('admitter',), 'operator': ('source_operator', 'recovery', 'revoker', 'reader')}


def authenticate(action, token):
    return Principal(principal_id=token, roles=ROLES[token]) if token in ROLES else None


@pytest.fixture(scope='module')
def sealed(fixture, tmp_path_factory):
    values = setup(fixture, tmp_path_factory.mktemp('upstream'))
    result = evaluate(values)
    archive, store, batch, _, request, _, _ = values
    before = archive.path.read_bytes(), store.path.read_bytes()
    sources = (SourceVersion(source_id='mock-1m', instance_id='mock-1m-instance', generation=result.archive_corpus_sha256),
        SourceVersion(source_id='mock-1n', instance_id='mock-1n-instance', generation=result.corpus_sha256))
    bundle = prepare_from_stage_a(archive, store, batch_id=batch.batch_id, batch_sha256=input_hash(batch),
        evaluation_id=request.request_id, evaluation_sha256=input_hash(result), bundle_id='bundle', prepared_by='prep', sources=sources)
    assert before == (archive.path.read_bytes(), store.path.read_bytes())
    return bundle


def new(tmp_path):
    c = EvidenceAdmissionCoordinator(tmp_path / 'authority.sqlite', authenticate=authenticate, clock=lambda: NOW,
        create_authority_id='SYNTHETIC-AUTHORITY')
    c.recover('initial-recovery', anchor=c.store.checkpoint(), token='operator', reason='synthetic bootstrap')
    return c


def prepare(c, bundle):
    for index, source in enumerate(bundle.sources):
        c.register_source('source-' + str(index), source, token='operator')
    c.prepare_bundle('prepare', bundle, token='prep')
    c.evaluate_bundle('evaluate', bundle.bundle_id, token='prep')


def review(c, bundle, **changes):
    return ReviewRequest(**(dict(review_id='review', bundle_id=bundle.bundle_id, bundle_sha256=input_hash(bundle),
        epoch=c.epoch, approved=True, expires_at=NOW + timedelta(days=1), reason='INVENTED REVIEW ONLY') | changes))


def ready(c, bundle, admit=True):
    prepare(c, bundle)
    c.record_review('review-op', review(c, bundle), token='reviewer')
    if admit:
        return c.admit_bundle('admit', bundle.bundle_id, review_id='review', expected_epoch=c.epoch, token='admitter')


def read(c, op='read'):
    return c.qualified_read(op, 'bundle', expected_epoch=c.epoch, token='operator')


def restart(c):
    return EvidenceAdmissionCoordinator(c.store.path, authenticate=authenticate, clock=lambda: NOW)


def test_whole_bundle_evaluation_authorization_and_provisional_isolation(tmp_path, sealed):
    c = new(tmp_path)
    prepare(c, sealed)
    assert c.replay()['states'] == {'bundle': 'PROVISIONAL'}
    with pytest.raises(AdmissionRejected): read(c, 'before-review')
    c.record_review('review-op', review(c, sealed), token='reviewer')
    assert c.replay()['states'] == {'bundle': 'REVIEWED'}
    with pytest.raises(AdmissionRejected): read(c, 'before-admit')
    receipt = c.admit_bundle('admit', 'bundle', review_id='review', expected_epoch=c.epoch, token='admitter')
    admitted = next(e for e in c.replay()['events'] if e['action'] == 'ADMIT')
    assert len(admitted['payload']['members']) == 6
    assert receipt.inspection_only and read(c).inspection_only
    assert all(not a.final for o in sealed.batch.observations for a in o.as_observed().availability)
    assert TrustRegistry().pins == ()
    assert c.replay() == c.replay()


@pytest.mark.parametrize('token', ['unknown', 'admitter'])
def test_authentication_roles(tmp_path, token):
    c = new(tmp_path)
    with pytest.raises(PermissionError): c.recover('unauthorized', anchor=c.store.checkpoint(), token=token)


@pytest.mark.parametrize('change', [{'epoch': 999}, {'bundle_sha256': '0' * 64}, {'expires_at': NOW}])
def test_stale_review(tmp_path, sealed, change):
    c = new(tmp_path); prepare(c, sealed)
    with pytest.raises(AdmissionRejected, match='STALE_REVIEW'):
        c.record_review('stale', review(c, sealed, **change), token='reviewer')
    assert c.lookup_operation('stale').event_action == 'DENIED'


def test_no_self_review_or_admission(tmp_path, sealed):
    c = new(tmp_path); prepare(c, sealed)
    with pytest.raises(AdmissionRejected, match='SELF_APPROVAL'):
        c.record_review('self-review', review(c, sealed), token='prep')
    c.record_review('review-op', review(c, sealed), token='reviewer')
    for token in ('prep', 'reviewer'):
        with pytest.raises(AdmissionRejected, match='INDEPENDENT_ADMISSION'):
            c.admit_bundle('self-admit-' + token, 'bundle', review_id='review', expected_epoch=c.epoch, token=token)


@pytest.mark.parametrize('approved', [True, False])
def test_competing_reviews_hold_even_previously_admitted_bundle(tmp_path, sealed, approved):
    c = new(tmp_path); ready(c, sealed)
    c.record_review('conflict', review(c, sealed, review_id='second', approved=approved), token='reviewer')
    assert c.replay()['states']['bundle'] == 'QUARANTINED'
    with pytest.raises(AdmissionRejected): read(c)


@pytest.mark.parametrize('bad', ['incomplete', 'raw', 'missing_dependency', 'real', 'policy', 'fx', 'upstream_review'])
def test_invalid_evidence_never_authorizes(tmp_path, sealed, bad):
    if bad == 'incomplete': bundle = sealed.model_copy(update={'observations': sealed.observations[:-1]})
    elif bad == 'real': bundle = sealed.model_copy(update={'scope': 'real'})
    elif bad == 'upstream_review':
        bundle = sealed.model_copy(update={'evaluation': sealed.evaluation.model_copy(update={'review_sha256': '0' * 64})})
    elif bad == 'policy':
        from tools.verified_daily_pipeline import VerifiedDailyInputs
        from tools.historical_snapshot import canonical_json
        p = VerifiedDailyInputs.model_validate_json(sealed.evaluation.synthetic_projection_json)
        p = p.model_copy(update={'verified_at': p.verified_at + timedelta(seconds=1)})
        bundle = sealed.model_copy(update={'evaluation': sealed.evaluation.model_copy(update={'synthetic_projection_json': canonical_json(p)})})
    else:
        obj = sealed.objects[0]
        change = {'body_b64': base64.b64encode(b'corrupt').decode()} if bad == 'raw' else (
            {'dependencies': ('missing',)} if bad == 'missing_dependency' else {'kind': 'fx_placeholder'})
        bundle = sealed.model_copy(update={'objects': (obj.model_copy(update=change), *sealed.objects[1:])})
    with pytest.raises(ValueError): validate_bundle(bundle)
    c = new(tmp_path)
    if bad == 'real':
        with pytest.raises(AdmissionRejected): c.prepare_bundle('prepare', bundle, token='prep')
    else:
        prepare(c, bundle)
        with pytest.raises(AdmissionRejected, match='BUNDLE_HELD_OR_REVOKED'):
            c.record_review('review-op', review(c, bundle), token='reviewer')
    assert c.replay()['states'].get('bundle') != 'ADMITTED' and TrustRegistry().pins == ()


@pytest.mark.parametrize('kind', ['bundle', 'object', 'source', 'review', 'grant', 'policy'])
def test_revocation_dependencies_restart_and_no_historical_capabilities(tmp_path, sealed, kind):
    c = new(tmp_path); ready(c, sealed); read(c)
    targets = {'bundle': 'bundle', 'object': sealed.objects[0].fingerprint(), 'source': sealed.sources[0].source_id,
        'review': 'review', 'grant': 'admit', 'policy': 'synthetic-policy-v1'}
    c.revoke('revoke', kind, targets[kind], reason='synthetic revocation', token='operator')
    assert c.replay()['states']['bundle'] == 'REVOKED'
    with pytest.raises(AdmissionRejected): read(c, 'after-revoke')
    with pytest.raises(AdmissionRejected): read(c, 'read')
    assert c.lookup_operation('read').inspection_only
    anchor = c.store.checkpoint(); other = restart(c)
    assert other.replay()['states']['bundle'] == 'REVOKED' and not other.replay()['serving']
    other.recover('recovery', anchor=anchor, token='operator', reason='synthetic recovery')
    assert other.replay()['states']['bundle'] == 'REVOKED'
    with pytest.raises(AdmissionRejected): read(c, 'stale-instance')


def test_restart_quarantines_grants_without_silent_recovery(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed); anchor = c.store.checkpoint()
    other = restart(c)
    with pytest.raises(AdmissionRejected): read(other)
    other.recover('recovery', anchor=anchor, token='operator', reason='synthetic recovery')
    assert other.replay()['serving'] and other.replay()['states']['bundle'] == 'QUARANTINED'
    with pytest.raises(AdmissionRejected): read(other, 'still-held')


def test_immutable_object_conflict_rolls_back_entire_prepare(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed)
    obj = sealed.objects[0].model_copy(update={'version': '2'})
    second = sealed.model_copy(update={'bundle_id': 'second', 'objects': (obj, *sealed.objects[1:])})
    with pytest.raises(AdmissionRejected, match='IMMUTABLE_OBJECT'):
        c.prepare_bundle('second-prepare', second, token='prep')
    assert set(c.replay()['states']) == {'bundle'}
    assert c.lookup_operation('second-prepare').event_action == 'DENIED'


def test_duplicate_and_competing_admission(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed, admit=False)
    barrier = Barrier(2)
    def attempt(op):
        barrier.wait()
        try: return c.admit_bundle(op, 'bundle', review_id='review', expected_epoch=c.epoch, token='admitter').event_action
        except AdmissionRejected: return 'rejected'
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(attempt, ['admit', 'competing']))
    assert sorted(outcomes) == ['ADMIT', 'rejected']
    op = next(e['operation_id'] for e in c.replay()['events'] if e['action'] == 'ADMIT')
    receipt = c.admit_bundle(op, 'bundle', review_id='review', expected_epoch=c.epoch, token='admitter')
    assert receipt.inspection_only and sum(e['action'] == 'ADMIT' for e in c.replay()['events']) == 1


@pytest.mark.parametrize('action', ['ADMIT', 'REVOKE'])
def test_interrupted_audit_transaction_has_no_partial_authority(tmp_path, sealed, action):
    c = new(tmp_path); ready(c, sealed, admit=action == 'REVOKE')
    before = c.replay()
    with closing(c.store.connect()) as db:
        db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON events WHEN json_extract(NEW.content,'$.action')='{action}' BEGIN SELECT RAISE(ABORT,'synthetic crash'); END")
    with pytest.raises(sqlite3.DatabaseError):
        if action == 'ADMIT': c.admit_bundle('crash', 'bundle', review_id='review', expected_epoch=c.epoch, token='admitter')
        else: c.revoke('crash', 'bundle', 'bundle', reason='test', token='operator')
    after = c.replay()
    assert before['states'] == after['states'] and before['events'] == after['events']
    assert not after['serving']
    with pytest.raises(PermissionError): read(c)
    assert restart(c).replay()['states']['bundle'] == 'QUARANTINED'


def test_lost_admission_ack_is_durable_but_process_held(tmp_path, sealed, monkeypatch):
    c = new(tmp_path); ready(c, sealed, admit=False)
    def crash(receipt): raise RuntimeError('lost acknowledgment')
    monkeypatch.setattr(c, '_after_commit', crash)
    with pytest.raises(RuntimeError): c.admit_bundle('admit', 'bundle', review_id='review', expected_epoch=c.epoch, token='admitter')
    assert c.lookup_operation('admit').event_action == 'ADMIT'
    assert not c.replay()['serving']
    assert restart(c).replay()['states']['bundle'] == 'QUARANTINED'


def test_revocation_race_serializes_current_use(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed)
    barrier = Barrier(2)
    def use():
        barrier.wait()
        try: return read(c).event_action
        except AdmissionRejected: return 'DENIED'
    def revoke():
        barrier.wait()
        return c.revoke('revoke', 'bundle', 'bundle', reason='race', token='operator')
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(use), pool.submit(revoke)
        outcome = a.result(); b.result()
    events = c.replay()['events']
    use_event = next(e for e in events if e['operation_id'] == 'read')
    rev = next(e for e in events if e['operation_id'] == 'revoke')
    assert (outcome == 'QUALIFIED_READ') == (use_event['sequence'] < rev['sequence'])
    assert c.replay()['states']['bundle'] == 'REVOKED'


def fenced(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed)
    source = sealed.sources[0]
    p = SyntheticEvidenceParticipant(tmp_path / 'mock.sqlite', create_source=source)
    f = c.begin_source_mutation('mutation', source.source_id, expected_generation=source.generation, token='operator')
    return c, p, f


def test_fence_apply_restart_finish_never_releases_old_bundle(tmp_path, sealed):
    c, p, f = fenced(tmp_path, sealed)
    with pytest.raises(AdmissionRejected): read(c)
    p.apply(c, f, new_generation='new-generation')
    anchor = c.store.checkpoint(); other = restart(c)
    with pytest.raises(AdmissionRejected): other.recover('blocked-recover', anchor=anchor, token='operator', reason='synthetic recovery')
    other.finish_source_mutation('finish', f, p, token='operator')
    other.recover('recover', anchor=anchor, token='operator', reason='synthetic recovery')
    assert not other.replay()['pending_mutations'] and other.replay()['states']['bundle'] == 'QUARANTINED'
    with pytest.raises(AdmissionRejected): read(other)


def test_abort_requires_durable_tombstone_and_blocks_late_apply(tmp_path, sealed):
    c, p, f = fenced(tmp_path, sealed)
    with pytest.raises(KeyError): c.abort_source_mutation('no-proof', f, p, token='operator')
    # Failed missing-proof reads do not modify authority.
    other = restart(c)
    p.abort(other, f, token='operator')
    with pytest.raises(AdmissionRejected): p.apply(other, f, new_generation='late')
    other.abort_source_mutation('abort', f, p, token='operator', reason='synthetic abort')
    assert not other.replay()['pending_mutations']
    assert p.load_receipt('mutation')['status'] == 'ABORTED'


@pytest.mark.parametrize('stage', ['before', 'after'])
def test_participant_crash_recovery(tmp_path, sealed, monkeypatch, stage):
    c, p, f = fenced(tmp_path, sealed)
    def crash(receipt): raise RuntimeError('injected interruption')
    monkeypatch.setattr(p, '_' + stage + '_commit', crash)
    with pytest.raises(RuntimeError): p.apply(c, f, new_generation='new-generation')
    monkeypatch.undo()
    assert c.replay()['pending_mutations']
    if stage == 'before':
        with pytest.raises(KeyError): p.load_receipt('mutation')
        p.abort(c, f, token='operator')
        c.abort_source_mutation('abort', f, p, token='operator', reason='synthetic abort')
    else:
        assert p.load_receipt('mutation')['status'] == 'APPLIED'
        with pytest.raises(AdmissionRejected): p.abort(c, f, token='operator')
        c.finish_source_mutation('finish', f, p, token='operator')
    assert c.replay()['states']['bundle'] == 'QUARANTINED'


def test_apply_abort_race_has_one_durable_outcome(tmp_path, sealed):
    c, p, f = fenced(tmp_path, sealed)
    barrier = Barrier(2)
    def act(apply):
        barrier.wait()
        try:
            return p.apply(c, f, new_generation='new-generation') if apply else p.abort(c, f, token='operator')
        except AdmissionRejected: return None
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(act, [True, False]))
    assert sum(v is not None for v in outcomes) == 1
    receipt = p.load_receipt('mutation')
    if receipt['status'] == 'APPLIED': c.finish_source_mutation('finish', f, p, token='operator')
    else: c.abort_source_mutation('abort', f, p, token='operator', reason='synthetic abort')
    assert not c.replay()['pending_mutations']


@pytest.mark.parametrize('tamper', ['tail', 'object', 'schema'])
def test_tampering_no_silent_repair(tmp_path, sealed, tamper):
    c = new(tmp_path); ready(c, sealed)
    with closing(c.store.connect()) as db:
        if tamper == 'tail': db.execute('DELETE FROM events WHERE sequence=(SELECT MAX(sequence) FROM events)')
        elif tamper == 'object': db.execute("UPDATE objects SET content='{}'")
        else: db.execute('PRAGMA user_version=99')
    with pytest.raises((ValueError, sqlite3.DatabaseError)): read(c)
    if tamper != 'object':
        with pytest.raises((ValueError, sqlite3.DatabaseError)): restart(c)


def test_wrong_checkpoint_fails_closed(tmp_path):
    c = new(tmp_path)
    anchor = c.store.checkpoint().model_copy(update={'sha256': 'f' * 64})
    with pytest.raises(AdmissionRejected): c.recover('bad-anchor', anchor=anchor, token='operator', reason='synthetic recovery')


def test_revoked_content_cannot_escape_by_alias(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed)
    c.revoke('revoke', 'object', sealed.objects[0].fingerprint(), reason='test', token='operator')
    obj = sealed.objects[0].model_copy(update={'object_id': 'alias'})
    second = sealed.model_copy(update={'bundle_id': 'alias-bundle', 'objects': (obj, *sealed.objects[1:]),
        'observations': (sealed.observations[0].model_copy(update={'object_id': 'alias'}), *sealed.observations[1:])})
    c.prepare_bundle('alias-prepare', second, token='prep')
    assert c.replay()['states']['alias-bundle'] == 'REVOKED'


@pytest.mark.parametrize('first', ['REVOKE', 'QUALIFIED_READ'])
def test_both_revocation_serializations_under_write_lock(tmp_path, sealed, monkeypatch, first):
    c = new(tmp_path); ready(c, sealed)
    entered, release, second_started = Event(), Event(), Event()
    original = c.store.append
    def append(db, **kwargs):
        if kwargs['action'] == first:
            entered.set()
            assert release.wait(10)
        return original(db, **kwargs)
    monkeypatch.setattr(c.store, 'append', append)
    def use():
        try: return read(c).event_action
        except AdmissionRejected: return 'DENIED'
    def revoke(): return c.revoke('revoke', 'bundle', 'bundle', reason='race', token='operator').event_action
    initial, following = (revoke, use) if first == 'REVOKE' else (use, revoke)
    def second():
        second_started.set()
        return following()
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(initial)
        assert entered.wait(10)
        b = pool.submit(second)
        assert second_started.wait(10)
        release.set()
        assert a.result() == first
        assert b.result() == ('DENIED' if first == 'REVOKE' else 'REVOKE')
    assert c.replay()['states']['bundle'] == 'REVOKED'


def test_abrupt_process_exit_rolls_back_uncommitted_sqlite_write(tmp_path, sealed):
    c = new(tmp_path); ready(c, sealed)
    before = c.replay()
    script = """import sqlite3,sys,os
db=sqlite3.connect(sys.argv[1],isolation_level=None)
db.execute('BEGIN IMMEDIATE')
db.execute('DELETE FROM bundles')
db.execute('DELETE FROM events')
os._exit(42)
"""
    result = subprocess.run([sys.executable, '-c', script, str(c.store.path)], check=False, timeout=15)
    assert result.returncode == 42
    assert c.replay() == before
    assert read(c).event_action == 'QUALIFIED_READ'


def test_source_instance_mismatch_cannot_clear_fence(tmp_path, sealed):
    c, p, f = fenced(tmp_path, sealed)
    wrong = SyntheticEvidenceParticipant(tmp_path / 'wrong.sqlite',
        create_source=sealed.sources[0].model_copy(update={'instance_id': 'wrong'}))
    with pytest.raises(AdmissionRejected, match='SOURCE_INSTANCE'):
        wrong.apply(c, f, new_generation='new')
    with pytest.raises(KeyError): c.finish_source_mutation('finish', f, wrong, token='operator')
    assert c.replay()['pending_mutations']


def test_recovery_races_finish_while_pending_fence_is_never_served(tmp_path, sealed):
    c, p, f = fenced(tmp_path, sealed)
    p.apply(c, f, new_generation='new')
    anchor = c.store.checkpoint(); other = restart(c)
    barrier = Barrier(2)
    def recover():
        barrier.wait()
        try: return other.recover('recover', anchor=anchor, token='operator', reason='synthetic recovery').event_action
        except AdmissionRejected: return 'DENIED'
    def finish():
        barrier.wait()
        return other.finish_source_mutation('finish', f, p, token='operator')
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(recover), pool.submit(finish)
        outcome = a.result(); b.result()
    state = other.replay()
    assert not state['pending_mutations'] and state['states']['bundle'] == 'QUARANTINED'
    assert state['serving'] == (outcome == 'RECOVER')
    with pytest.raises(AdmissionRejected): read(other)


def test_missing_store_is_not_recreated(tmp_path):
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError):
        EvidenceAdmissionCoordinator(path, authenticate=authenticate, clock=lambda: NOW)
    assert not path.exists()


def test_recovery_requires_audited_reason(tmp_path):
    c = new(tmp_path); other = restart(c)
    with pytest.raises(AdmissionRejected, match='RECOVERY_REASON_REQUIRED'):
        other.recover('no-reason', anchor=c.store.checkpoint(), token='operator')
    assert not other.replay()['serving']
    assert other.lookup_operation('no-reason').event_action == 'DENIED'
