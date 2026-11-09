"""Synthetic, offline recovery drills and deterministic crash boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import Event

import pytest

from providers.paper_broker import PaperBroker
from tools import backup_recovery as recovery
from tools.operational_monitoring import capture_database
from tools.restore_quarantine import read_restore_fence
from tests.test_gated_execution import accepted, request, NOW


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.sqlite'
    with PaperBroker(path, strict=True) as broker:
        accepted(broker)
        assert broker.execute_gated(request(broker)).status == 'FILLED'
        accepted(broker, 'pending', ticker='MSFT')
    return path


def backup(source, tmp_path, identity='backup1'):
    return recovery.create_backup(source, tmp_path / 'backups', backup_id=identity, timestamp=NOW)


def restore(artifact, tmp_path, **changes):
    options = dict(expected_manifest_sha256=artifact['manifest_sha256'], journal=tmp_path / 'restore-audit.sqlite',
        restore_id='restore1', operator_id='operator', authorization_id='approval', reason='Synthetic recovery drill',
        timestamp=NOW, authorize=lambda request: True)
    options.update(changes)
    return recovery.restore_backup(artifact['path'], tmp_path / 'restore1', **options)


def events(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'restore-audit.sqlite')) as db:
        return [r[0] for r in db.execute('SELECT action FROM restore_events ORDER BY sequence')]


def tables(path):
    return json.loads(capture_database(path).content)['tables']


def test_populated_backup_restore_preserves_history_and_restart_fence(source, tmp_path):
    original = source.read_bytes()
    artifact = backup(source, tmp_path)
    result = restore(artifact, tmp_path)
    target = Path(result['path']) / 'ledger.sqlite'
    assert source.read_bytes() == original
    before, after = tables(source), tables(target)
    assert {k: v for k, v in after.items() if k != 'restore_fence'} == before
    assert events(tmp_path) == ['PREPARED', 'SEALED', 'PUBLISHED']
    assert restore(artifact, tmp_path) == result
    for attempt in ('after-restore', 'after-restart'):
        with PaperBroker(target) as broker:
            outcome = broker.execute_gated(request(broker, 'pending', attempt))
            assert outcome.status == 'REJECTED'
            assert 'RESTORE_QUARANTINE' in str(outcome.reasons)
            assert outcome.before == outcome.after
            assert len(broker.fills()) == 1
            with pytest.raises(ValueError, match='direct manual'):
                broker.simulate_fill('pending', price=100, timestamp=NOW)
            with broker._transaction():
                broker._gate_active = broker._integrity_checked = True
                with pytest.raises(ValueError, match='RESTORE_QUARANTINE'):
                    broker._simulate_fill_locked('pending', 100, 0, 0, NOW.isoformat())
    assert events(tmp_path)[-1] == 'PUBLISHED'


def test_original_unquarantined_and_legacy_behavior_unchanged(source, tmp_path):
    artifact = backup(source, tmp_path)
    restore(artifact, tmp_path)
    with PaperBroker(source) as broker:
        assert broker._db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert read_restore_fence(broker._db) is None
        assert broker.execute_gated(request(broker, 'pending', 'original')).status == 'FILLED'
    legacy = tmp_path / 'legacy.sqlite'
    with PaperBroker(legacy) as broker:
        accepted(broker)
        broker.simulate_fill('buy', price=100, timestamp=NOW)
    old = backup(legacy, tmp_path, 'legacy')
    with pytest.raises(ValueError, match='version-3'):
        restore(old, tmp_path, journal=tmp_path / 'legacy-audit.sqlite')


@pytest.mark.parametrize('member', ['manifest.json', 'verification.json', 'ledger.sqlite'])
@pytest.mark.parametrize('mutation', ['missing', 'corrupt'])
def test_missing_and_corrupt_bundle_evidence_fails_closed(source, tmp_path, member, mutation):
    artifact = backup(source, tmp_path)
    path = Path(artifact['path']) / member
    if mutation == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'corrupt')
    with pytest.raises((ValueError, OSError)):
        restore(artifact, tmp_path)
    assert not (tmp_path / 'restore1').exists()
    assert events(tmp_path)[-1] == 'FAILED'


@pytest.mark.parametrize('sql', [
    "UPDATE account SET cash='9999'", 'DELETE FROM audit', 'DELETE FROM gate_attempts',
    'PRAGMA user_version=99', 'DROP TABLE operational_events',
    "UPDATE operational_control SET blocked=1,block_id='missing',report_sha256='bad',activated_at='bad'",
])
def test_independent_financial_schema_and_audit_checks(source, tmp_path, sql):
    with closing(sqlite3.connect(source)) as db:
        db.execute(sql)
        db.commit()
    with pytest.raises((ValueError, sqlite3.Error)):
        backup(source, tmp_path)
    assert not (tmp_path / 'backups' / 'backup1').exists()


@pytest.mark.parametrize('authorize', [None, lambda r: False, lambda r: 1])
def test_authorization_required_and_denial_durable(source, tmp_path, authorize):
    artifact = backup(source, tmp_path)
    with pytest.raises(PermissionError):
        restore(artifact, tmp_path, authorize=authorize)
    assert events(tmp_path) == ['DENIED']
    assert not (tmp_path / 'restore1').exists()


@pytest.mark.parametrize('boundary', ['copy', 'seal', 'publish'])
def test_interrupted_backup_never_appears_published(source, tmp_path, monkeypatch, boundary):
    def fail(*args, **kwargs):
        raise OSError('injected backup interruption')
    monkeypatch.setattr(recovery, {'copy': '_copy_online', 'seal': '_seal', 'publish': '_publish'}[boundary], fail)
    original = source.read_bytes()
    with pytest.raises(OSError):
        backup(source, tmp_path)
    assert source.read_bytes() == original
    assert not (tmp_path / 'backups' / 'backup1').exists()
    for stage in (tmp_path / 'backups').iterdir():
        with pytest.raises(ValueError, match='published'):
            recovery.verify_bundle(stage, expected_manifest_sha256='0' * 64)


@pytest.mark.parametrize('boundary', ['copy', 'fence', 'seal', 'publish'])
def test_interrupted_restore_preserves_source_and_has_failed_audit(source, tmp_path, monkeypatch, boundary):
    artifact = backup(source, tmp_path)
    def fail(*args, **kwargs):
        raise OSError('injected restore interruption')
    monkeypatch.setattr(recovery, {'copy': '_copy_online', 'fence': 'install_restore_fence',
        'seal': '_seal', 'publish': '_publish'}[boundary], fail)
    original = source.read_bytes()
    with pytest.raises(OSError):
        restore(artifact, tmp_path)
    assert source.read_bytes() == original
    assert not (tmp_path / 'restore1').exists()
    assert events(tmp_path)[-1] == 'FAILED'


def test_post_publication_audit_failure_retry_never_overwrites(source, tmp_path, monkeypatch):
    artifact = backup(source, tmp_path)
    real = recovery._journal_event
    def fail(journal, request, action, detail):
        if action == 'PUBLISHED':
            raise OSError('journal unavailable after publication')
        return real(journal, request, action, detail)
    monkeypatch.setattr(recovery, '_journal_event', fail)
    with pytest.raises(OSError):
        restore(artifact, tmp_path)
    target = tmp_path / 'restore1' / 'ledger.sqlite'
    original = target.read_bytes()
    with PaperBroker(target) as broker:
        assert read_restore_fence(broker._db)
    monkeypatch.setattr(recovery, '_journal_event', real)
    result = restore(artifact, tmp_path)
    assert result['quarantined'] and target.read_bytes() == original
    assert events(tmp_path) == ['PREPARED', 'SEALED', 'FAILED', 'PREPARED', 'PUBLISHED']


@pytest.mark.parametrize('kind', ['file', 'directory', 'active_ledger'])
def test_existing_destination_preserved(source, tmp_path, kind):
    artifact = backup(source, tmp_path)
    target = tmp_path / 'restore1'
    if kind == 'file':
        target.write_bytes(b'precious existing file')
    else:
        target.mkdir()
        with PaperBroker(target / 'ledger.sqlite', strict=True):
            pass
    saved = (target if kind == 'file' else target / 'ledger.sqlite').read_bytes()
    active = PaperBroker(target / 'ledger.sqlite') if kind == 'active_ledger' else None
    try:
        with pytest.raises((ValueError, OSError)):
            restore(artifact, tmp_path)
    finally:
        if active is not None:
            active.close()
    assert saved == (target if kind == 'file' else target / 'ledger.sqlite').read_bytes()


def test_backup_publication_race_never_clobbers(source, tmp_path, monkeypatch):
    real = recovery._publish
    def race(stage, target):
        target.mkdir()
        (target / 'owner').write_text('winner')
        real(stage, target)
    monkeypatch.setattr(recovery, '_publish', race)
    with pytest.raises(OSError):
        backup(source, tmp_path)
    assert (tmp_path / 'backups' / 'backup1' / 'owner').read_text() == 'winner'


def test_duplicate_backup_identity_is_no_clobber(source, tmp_path):
    artifact = backup(source, tmp_path)
    before = (Path(artifact['path']) / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        backup(source, tmp_path)
    assert before == (Path(artifact['path']) / 'manifest.json').read_bytes()


@pytest.mark.parametrize('mutation', [
    'DROP TABLE restore_fence', 'DELETE FROM restore_fence',
    "UPDATE restore_fence SET receipt_sha256='bad'", 'PRAGMA user_version=3',
])
def test_missing_or_inconsistent_fence_rejected_after_restart(source, tmp_path, mutation):
    target = Path(restore(backup(source, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    with closing(sqlite3.connect(target)) as db:
        db.execute(mutation)
        db.commit()
    with pytest.raises((ValueError, sqlite3.Error)):
        PaperBroker(target)


def test_old_backup_cannot_reactivate_later_kill_switch(source, tmp_path):
    artifact = backup(source, tmp_path)
    with PaperBroker(source) as broker:
        broker.set_kill_switch(True, timestamp=NOW, reason='Later emergency')
    target = Path(restore(artifact, tmp_path)['path']) / 'ledger.sqlite'
    with PaperBroker(target) as broker:
        assert not broker.portfolio().kill_switch  # Exact historic state preserved.
        broker.set_kill_switch(False, timestamp=NOW, reason='Independent switch')
        assert broker.execute_gated(request(broker, 'pending', 'old')).status == 'REJECTED'
        assert read_restore_fence(broker._db)
    with PaperBroker(source) as broker:
        assert broker.portfolio().kill_switch


def test_wal_online_backup_captures_consistent_committed_writer_state(source, tmp_path, monkeypatch):
    copied = Event()
    real = recovery._copy_online
    def copy(src, dst):
        # Deterministic overlapping open writer, with an uncommitted order.
        with closing(sqlite3.connect(src, isolation_level=None)) as writer:
            assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("UPDATE account SET cash='999' WHERE id=1")
            with ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(real, src, dst)
                task.result(timeout=10)
            copied.set()
            writer.execute('ROLLBACK')
    monkeypatch.setattr(recovery, '_copy_online', copy)
    artifact = backup(source, tmp_path)
    assert copied.is_set()
    assert tables(source) == tables(Path(artifact['path']) / 'ledger.sqlite')
    assert not list(Path(artifact['path']).glob('*-wal'))


def test_concurrent_quarantined_fills_remain_rejected(source, tmp_path):
    target = Path(restore(backup(source, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    def fill(identity):
        with PaperBroker(target) as broker:
            return broker.execute_gated(request(broker, 'pending', identity)).status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(fill, ['race1', 'race2'])) == ['REJECTED', 'REJECTED']
    with PaperBroker(target) as broker:
        assert len(broker.fills()) == 1


def test_current_verifier_rejects_rehashed_invalid_financial_image(source, tmp_path):
    artifact = backup(source, tmp_path)
    bundle = Path(artifact['path'])
    with closing(sqlite3.connect(bundle / 'ledger.sqlite')) as db:
        db.execute("UPDATE account SET cash='99999'")
        db.commit()
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    manifest['database_sha256'] = sha256((bundle / 'ledger.sqlite').read_bytes()).hexdigest()
    data = recovery._canonical(manifest)
    (bundle / 'manifest.json').write_bytes(data)
    with pytest.raises(ValueError, match='verification failed'):
        recovery.verify_bundle(bundle, expected_manifest_sha256=sha256(data).hexdigest())


def test_kill_and_operational_latch_preserved_independently_of_fence(source, tmp_path):
    from tests.test_operational_monitoring import activate, report, recovery as release_request
    from tools.operational_controls import release_operational_block
    # Deliberately introduce and explicitly correct a synthetic fixture fault.
    # Neither monitoring nor restore performs this repair.
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE account SET cash='9999'")
        db.commit()
    activate(source, report(source))
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE account SET cash='9000'")
        db.commit()
    with PaperBroker(source) as broker:
        broker.set_kill_switch(True, timestamp=NOW, reason='Retain emergency switch')
    target = Path(restore(backup(source, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    original = tables(source)
    assert tables(target)['operational_events'] == original['operational_events']
    assert tables(target)['operational_control'] == original['operational_control']
    with PaperBroker(target) as broker:
        assert broker.portfolio().kill_switch
        broker.set_kill_switch(False, timestamp=NOW, reason='Only clears kill')
    current = report(target)
    assert current.operational_block and current.status != 'CRITICAL', current.findings
    release_operational_block(target, release_request(current), current, authorize=lambda req, report: True)
    with PaperBroker(target) as broker:
        assert not broker.portfolio().kill_switch
        assert read_restore_fence(broker._db)
        result = broker.execute_gated(request(broker, 'pending', 'independent-controls'))
        assert 'RESTORE_QUARANTINE' in str(result.reasons)
    assert report(target).status != 'CRITICAL'


def test_cached_completed_attempt_cannot_duplicate_a_fill_after_restore(source, tmp_path):
    with PaperBroker(source) as broker:
        original = broker.execution_attempt('attempt')
    target = Path(restore(backup(source, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    with PaperBroker(target) as broker:
        assert broker.execute_gated(original.request) == original
        assert len(broker.fills()) == 1
        assert broker.execute_gated(request(broker, 'buy', 'new-buy')).status == 'REJECTED'
        assert len(broker.fills()) == 1


def test_authorization_callback_exception_is_audited(source, tmp_path):
    artifact = backup(source, tmp_path)
    def fail(request):
        raise RuntimeError('authorizer offline')
    with pytest.raises(RuntimeError, match='authorizer offline'):
        restore(artifact, tmp_path, authorize=fail)
    assert events(tmp_path) == ['DENIED']


@pytest.mark.parametrize('boundary', ['PREPARED', 'SEALED'])
def test_required_audit_failure_prevents_publication(source, tmp_path, monkeypatch, boundary):
    artifact = backup(source, tmp_path)
    real = recovery._journal_event
    def fail(journal, request, action, detail):
        if action == boundary:
            raise OSError('required audit unavailable')
        real(journal, request, action, detail)
    monkeypatch.setattr(recovery, '_journal_event', fail)
    with pytest.raises(OSError):
        restore(artifact, tmp_path)
    assert not (tmp_path / 'restore1').exists()


def test_restore_publication_race_keeps_existing_ledger(source, tmp_path, monkeypatch):
    artifact = backup(source, tmp_path)
    real = recovery._publish
    def race(stage, target):
        target.mkdir()
        with PaperBroker(target / 'ledger.sqlite', strict=True):
            pass
        real(stage, target)
    monkeypatch.setattr(recovery, '_publish', race)
    with pytest.raises(OSError):
        restore(artifact, tmp_path)
    with PaperBroker(tmp_path / 'restore1' / 'ledger.sqlite') as broker:
        assert read_restore_fence(broker._db) is None
        assert not broker.fills()
    assert events(tmp_path)[-1] == 'FAILED'


def test_first_fill_racing_publication_observes_committed_fence(source, tmp_path, monkeypatch):
    artifact = backup(source, tmp_path)
    real = recovery._publish
    statuses = []
    def publish(stage, target):
        real(stage, target)
        with ThreadPoolExecutor(max_workers=1) as pool:
            def first_fill():
                with PaperBroker(target / 'ledger.sqlite') as broker:
                    return broker.execute_gated(request(broker, 'pending', 'first-observer')).status
            statuses.append(pool.submit(first_fill).result(timeout=10))
    monkeypatch.setattr(recovery, '_publish', publish)
    # Rejection audit changed the image after publication. Do not reseal it or
    # falsely claim the original publication seal still matches.
    with pytest.raises(ValueError, match='hash mismatch'):
        restore(artifact, tmp_path)
    assert statuses == ['REJECTED']
    with PaperBroker(tmp_path / 'restore1' / 'ledger.sqlite') as broker:
        assert read_restore_fence(broker._db) and len(broker.fills()) == 1


def test_restore_id_conflict_and_corrupt_journal_refuse(source, tmp_path):
    artifact = backup(source, tmp_path)
    result = restore(artifact, tmp_path)
    before = (Path(result['path']) / 'ledger.sqlite').read_bytes()
    with pytest.raises(ValueError, match='Conflicting'):
        restore(artifact, tmp_path, reason='Different authorization scope')
    with closing(sqlite3.connect(tmp_path / 'restore-audit.sqlite')) as db:
        db.execute("UPDATE restore_events SET sha256='broken'")
        db.commit()
    with pytest.raises(ValueError, match='audit integrity'):
        restore(artifact, tmp_path)
    assert before == (Path(result['path']) / 'ledger.sqlite').read_bytes()


def test_progress_cancellation_leaves_no_published_backup(source, tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'MAX_STEPS', 0)
    with pytest.raises(ValueError, match='resource budget'):
        backup(source, tmp_path)
    assert not (tmp_path / 'backups' / 'backup1').exists()


def test_size_budget_refuses_backup(source, tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'MAX_BYTES', 1)
    with pytest.raises(ValueError, match='size budget'):
        backup(source, tmp_path)


def test_bundle_relabel_manifest_hash_and_evidence_identity(source, tmp_path):
    artifact = backup(source, tmp_path)
    bundle = Path(artifact['path'])
    renamed = bundle.with_name('renamed')
    bundle.rename(renamed)
    with pytest.raises(ValueError, match='identity'):
        recovery.verify_bundle(renamed, expected_manifest_sha256=artifact['manifest_sha256'])
    renamed.rename(bundle)
    with pytest.raises(ValueError, match='Manifest hash'):
        recovery.verify_bundle(bundle, expected_manifest_sha256='0' * 64)


def test_missing_bundle_does_not_create_source(tmp_path):
    with pytest.raises(ValueError):
        recovery.verify_bundle(tmp_path / 'missing', expected_manifest_sha256='0' * 64)
    assert not (tmp_path / 'missing').exists()


def test_orchestration_cannot_bypass_restore_fence(tmp_path, signals):
    from tests.test_paper_orchestration import staged, plan, authorize
    from tools.paper_orchestration import WorkflowStore, preview_workflow, execute_workflow
    path = tmp_path / 'workflow-source.sqlite'
    with PaperBroker(path, strict=True) as broker:
        staged(broker, signals[-1])
    target = Path(restore(backup(path, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    store = WorkflowStore(tmp_path / 'workflow.sqlite')
    with PaperBroker(target) as broker:
        value = plan(broker, signals)
        preview = preview_workflow(value, broker=broker, store=store, preview_at=signals[-1], trust=signals[3])
        result = execute_workflow(value.run_id, authorization=authorize(preview, signals[-1]),
            broker=broker, store=store, trust=signals[3])
        assert not broker.fills()
        assert any('RESTORE_QUARANTINE' in str(step.outcome.reasons) for step in result.steps if step.outcome)


def test_deterministic_manifest_and_read_only_verification(source, tmp_path):
    first = backup(source, tmp_path)
    second = recovery.create_backup(source, tmp_path / 'second-root', backup_id='backup1', timestamp=NOW)
    assert first['manifest_sha256'] == second['manifest_sha256']
    bundle = Path(first['path'])
    original = {p.name: p.read_bytes() for p in bundle.iterdir()}
    recovery.verify_bundle(bundle, expected_manifest_sha256=first['manifest_sha256'])
    assert original == {p.name: p.read_bytes() for p in bundle.iterdir()}


def test_historical_source_warning_is_narrowly_scoped(source, tmp_path, monkeypatch):
    from tools import operational_monitoring
    monkeypatch.setattr(operational_monitoring, 'gate_source_hash', lambda: '0' * 64)
    artifact = backup(source, tmp_path)
    manifest = recovery.verify_bundle(artifact['path'], expected_manifest_sha256=artifact['manifest_sha256'])
    evidence = json.loads((Path(artifact['path']) / 'verification.json').read_bytes())
    assert {f['code'] for f in evidence['findings']} == {'REPLAY_ENVIRONMENT_UNAVAILABLE'}
    assert manifest['facts']['counts']['fills'] == 1


@pytest.mark.parametrize('member', ['manifest.json', 'verification.json'])
def test_rehashed_inconsistent_evidence_rejected(source, tmp_path, member):
    artifact = backup(source, tmp_path)
    bundle = Path(artifact['path'])
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    if member == 'verification.json':
        evidence = json.loads((bundle / member).read_bytes())
        evidence['cash_eur'] = '1'
        data = recovery._canonical(evidence)
        (bundle / member).write_bytes(data)
        manifest['verification_sha256'] = sha256(data).hexdigest()
    else:
        manifest['facts']['counts']['fills'] = 99
    data = recovery._canonical(manifest)
    (bundle / 'manifest.json').write_bytes(data)
    with pytest.raises(ValueError, match='conflict'):
        recovery.verify_bundle(bundle, expected_manifest_sha256=sha256(data).hexdigest())


def test_rehashed_corrupt_sqlite_refused(source, tmp_path):
    artifact = backup(source, tmp_path)
    bundle = Path(artifact['path'])
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    (bundle / 'ledger.sqlite').write_bytes(b'not a sqlite database')
    manifest['database_bytes'] = (bundle / 'ledger.sqlite').stat().st_size
    manifest['database_sha256'] = sha256((bundle / 'ledger.sqlite').read_bytes()).hexdigest()
    data = recovery._canonical(manifest)
    (bundle / 'manifest.json').write_bytes(data)
    with pytest.raises((ValueError, sqlite3.Error)):
        recovery.verify_bundle(bundle, expected_manifest_sha256=sha256(data).hexdigest())


def test_unsupported_publication_platform_fails_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    stage, target = tmp_path / 'stage', tmp_path / 'target'
    stage.mkdir()
    monkeypatch.setattr(recovery, 'os', SimpleNamespace(name='posix'))
    with pytest.raises(RuntimeError, match='Windows only'):
        recovery._publish(stage, target)
    assert stage.exists() and not target.exists()


def test_wal_writer_commits_between_online_backup_steps(source, tmp_path, monkeypatch):
    with closing(sqlite3.connect(source)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE padding (id INTEGER PRIMARY KEY, payload TEXT)')
        db.execute('INSERT INTO padding VALUES (1,?)', ('x' * 700000,))
        db.commit()
    real_ro = recovery._ro
    committed = []
    class Source:
        def __init__(self, db):
            self.db = db
        def __getattr__(self, name):
            return getattr(self.db, name)
        def backup(self, dst, **options):
            progress = options['progress']
            def overlap(status, remaining, total):
                if not committed and remaining:
                    def write():
                        with PaperBroker(source) as broker:
                            accepted(broker, 'during-backup', ticker='AMZN')
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(write).result(timeout=10)
                    committed.append(True)
                progress(status, remaining, total)
            self.db.backup(dst, pages=1, progress=overlap, sleep=0.01)
    def ro(path):
        db = real_ro(path)
        return Source(db) if Path(path) == source else db
    monkeypatch.setattr(recovery, '_ro', ro)
    artifact = backup(source, tmp_path)
    assert committed
    assert tables(source) == tables(Path(artifact['path']) / 'ledger.sqlite')


def test_simultaneous_duplicate_restores_publish_at_most_one_image(source, tmp_path):
    from threading import Barrier
    artifact = backup(source, tmp_path)
    barrier = Barrier(2)
    def run():
        def authorized(request):
            barrier.wait(timeout=10)
            return True
        try:
            return restore(artifact, tmp_path, authorize=authorized)
        except (ValueError, OSError):
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: run(), range(2)))
    assert any(value for value in values)
    with PaperBroker(tmp_path / 'restore1' / 'ledger.sqlite') as broker:
        assert read_restore_fence(broker._db)
        assert len(broker.fills()) == 1


def test_recovery_racing_strict_fill_cannot_release_restore_fence(source, tmp_path, monkeypatch):
    from tests.test_operational_monitoring import activate, report, recovery as release_request
    from tools.operational_controls import release_operational_block
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE account SET cash='9999'")
        db.commit()
    activate(source, report(source))
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE account SET cash='9000'")
        db.commit()
    target = Path(restore(backup(source, tmp_path), tmp_path)['path']) / 'ledger.sqlite'
    current = report(target)
    inside, proceed, started = Event(), Event(), Event()
    def authorized(req, observed):
        inside.set()
        assert proceed.wait(10)
        return True
    def fill():
        started.set()
        with PaperBroker(target) as broker:
            return broker.execute_gated(request(broker, 'pending', 'recovery-race'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        releasing = pool.submit(release_operational_block, target, release_request(current), current, authorize=authorized)
        assert inside.wait(10)
        filling = pool.submit(fill)
        assert started.wait(10)
        assert not filling.done()
        proceed.set()
        assert releasing.result(timeout=10)['action'] == 'RELEASED'
        assert 'RESTORE_QUARANTINE' in str(filling.result(timeout=10).reasons)


def test_restore_journal_cannot_be_an_existing_financial_ledger(source, tmp_path):
    artifact = backup(source, tmp_path)
    original = source.read_bytes()
    with pytest.raises(ValueError, match='journal'):
        restore(artifact, tmp_path, journal=source)
    assert source.read_bytes() == original
    assert not (tmp_path / 'restore1').exists()


def test_backup_change_between_verification_and_copy_refuses_restore(source, tmp_path, monkeypatch):
    artifact = backup(source, tmp_path)
    real = recovery._copy_online
    original = source.read_bytes()
    def changed(src, dst):
        with closing(sqlite3.connect(src)) as db:
            db.execute("UPDATE account SET cash='1'")
            db.commit()
        real(src, dst)
    monkeypatch.setattr(recovery, '_copy_online', changed)
    with pytest.raises(ValueError, match='Source changed'):
        restore(artifact, tmp_path)
    assert source.read_bytes() == original
    assert not (tmp_path / 'restore1').exists()
    assert events(tmp_path)[-1] == 'FAILED'


# Reuse deterministic offline market fixtures solely to exercise orchestration.
from tests.test_market_verification import fixture
from tests.test_paper_orchestration import signals
