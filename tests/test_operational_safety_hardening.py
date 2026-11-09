from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import sqlite3
from statistics import median
from threading import Barrier, Event
from time import perf_counter

import pytest

from providers.paper_broker import PaperBroker
from tests.test_gated_execution import accepted, request, NOW
from tests.test_operational_monitoring import report, activate, recovery, codes
from tools import operational_controls as controls
from tools.historical_snapshot import input_hash
from tools.operational_monitoring import capture_database, monitor


class ConnectionProxy:
    """Test-only SQL boundary faults, including successful commit/lost response."""
    def __init__(self, inner, hook):
        object.__setattr__(self, 'inner', inner)
        object.__setattr__(self, 'hook', hook)

    def __getattr__(self, name): return getattr(self.inner, name)
    def __setattr__(self, name, value): setattr(self.inner, name, value)

    def execute(self, sql, *args):
        self.hook(sql, 'before')
        result = self.inner.execute(sql, *args)
        self.hook(sql, 'after')
        return result


def test_preflight_latches_critical_before_new_fill_and_preserves_rejection_contract(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        b._db.execute('DELETE FROM gate_attempts')
        accepted(b, 'next', ticker='MSFT', quantity=1)
        req = request(b, 'next', 'next')
        outcome = b.execute_gated(req)
        assert outcome.status == 'REJECTED' and 'OPERATIONAL_BLOCK' in outcome.reasons[0]
        assert outcome.before == outcome.after  # Latch is outside rejection savepoint.
        assert len(b.fills()) == 1 and b.portfolio().available_cash == 9000
        event = json.loads(b._db.execute('SELECT content_json FROM operational_events').fetchone()[0])
        assert event['origin'] == 'strict_preflight'
        assert any(f['code'] == 'STRICT_FILL_WITHOUT_GATE' for f in event['findings'])
    with PaperBroker(path) as b:
        assert b.execute_gated(req) == outcome
        assert report(path).operational_block is True and len(b.fills()) == 1


def test_healthy_manual_check_is_read_only_and_does_not_release_active_latch(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True): pass
    before = capture_database(path)
    result = controls.reconcile_and_latch(path, report_id='check', timestamp=NOW, activation_id='latch',
        operator_id='operator', reason='explicit manual inspection')
    assert result.report.status == 'HEALTHY' and result.block_id is None
    assert result.activation_json is None and capture_database(path) == before
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='9999'")
    result = controls.reconcile_and_latch(path, report_id='critical', timestamp=NOW, activation_id='latch',
        operator_id='operator', reason='explicit manual inspection')
    assert result.report.status == 'CRITICAL' and result.block_id == 'latch'
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    result = controls.reconcile_and_latch(path, report_id='healthy', timestamp=NOW, activation_id='different',
        operator_id='operator', reason='inspect after investigation')
    assert result.report.status == 'HEALTHY' and result.block_id == 'latch' and result.activation_json is None


@pytest.mark.parametrize('stage', ['UPDATE account SET cash=', 'INSERT INTO fills', 'COMMIT'])
def test_injected_before_commit_and_fill_faults_reopen_consistently(tmp_path, stage):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
        before = b.execution_state()
        fired = False
        def hook(sql, when):
            nonlocal fired
            target = 'before' if stage == 'COMMIT' else 'after'
            if not fired and sql.startswith(stage) and when == target:
                fired = True
                raise OSError('controlled pre-commit/fill failure')
        original = b._db
        b._db = ConnectionProxy(original, hook)
        if stage == 'COMMIT':
            with pytest.raises(OSError, match='controlled'): b.execute_gated(req)
            assert b.execution_state() == before
            with pytest.raises(KeyError): b.execution_attempt(req.attempt_id)
        else:
            outcome = b.execute_gated(req)
            assert outcome.status == 'REJECTED' and outcome.before == outcome.after == before
        assert fired and not b.fills()
    with PaperBroker(path) as b:
        assert b.reconcile().available_cash == 10000 and b.get_order('buy').status == 'ACCEPTED'


def test_lost_commit_acknowledgement_preserves_original_error_and_exact_retry(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
        fired = False
        def hook(sql, when):
            nonlocal fired
            if sql == 'COMMIT' and when == 'after' and not fired:
                fired = True
                raise OSError('commit acknowledgement lost')
        b._db = ConnectionProxy(b._db, hook)
        with pytest.raises(OSError, match='acknowledgement lost'): b.execute_gated(req)
        assert not b._db.in_transaction
    with PaperBroker(path) as b:
        committed = b.execution_attempt(req.attempt_id)
        assert committed.status == 'FILLED' and b.execute_gated(req) == committed
        assert len(b.fills()) == 1 and b.reconcile().available_cash == 9000


def test_whole_transaction_abort_does_not_invent_rejection_audit(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
        before = b.execution_state()
        b._db.execute("CREATE TRIGGER abort_all BEFORE INSERT ON fills BEGIN SELECT RAISE(ROLLBACK,'whole transaction aborted'); END")
        with pytest.raises(sqlite3.IntegrityError, match='whole transaction aborted'): b.execute_gated(req)
        assert b.execution_state() == before and not b.fills()
        with pytest.raises(KeyError): b.execution_attempt(req.attempt_id)
    with PaperBroker(path) as b: assert b.reconcile().available_cash == 10000


def test_failed_preflight_latch_audit_refuses_every_retry_without_false_durability(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute("UPDATE account SET cash='9999'")
        req = request(b)
        b._db.execute("CREATE TRIGGER fail_control BEFORE INSERT ON operational_events BEGIN SELECT RAISE(ABORT,'control audit unavailable'); END")
        for _ in range(2):
            with pytest.raises(sqlite3.IntegrityError, match='control audit unavailable'): b.execute_gated(req)
            assert not b.fills()
            assert b._db.execute('SELECT blocked FROM operational_control').fetchone()[0] == 0
            assert b._db.execute('SELECT count(*) FROM operational_events').fetchone()[0] == 0
        b._db.execute('DROP TRIGGER fail_control')
        rejected = b.execute_gated(req)
        assert rejected.status == 'REJECTED' and report(path).operational_block
        b._db.execute("UPDATE account SET cash='10000'")  # Explicit synthetic fixture repair only.
        healthy = report(path)
        recovered = recovery(healthy, block='preflight:' + input_hash(req))
        controls.release_operational_block(path, recovered, healthy, authorize=lambda req, report: True)
        assert b.execute_gated(req) == rejected and not b.fills()  # Recovery never reauthorizes it.
        assert b.execute_gated(request(b, attempt='fresh-authorized-attempt')).status == 'FILLED'


def test_recovery_clear_before_audit_failure_rolls_back_latch_and_kill(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b: b._db.execute("UPDATE account SET cash='9999'")
    activate(path, report(path))
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    with PaperBroker(path) as b:
        b.set_kill_switch(True, timestamp=NOW, reason='independent kill remains')
        b._db.execute("CREATE TRIGGER recovery_fault BEFORE INSERT ON operational_events WHEN NEW.event_id='faulty-release' BEGIN SELECT RAISE(ABORT,'recovery audit failed'); END")
    healthy = report(path)
    with pytest.raises(sqlite3.IntegrityError, match='recovery audit failed'):
        controls.release_operational_block(path, recovery(healthy, 'faulty-release'), healthy, authorize=lambda req, report: True)
    with PaperBroker(path) as b:
        assert report(path).operational_block is True and b.portfolio().kill_switch is True
        assert b._db.execute('SELECT count(*) FROM operational_events').fetchone()[0] == 1


def test_migration_stage_fault_rolls_back_all_metadata_and_original_rows(tmp_path, monkeypatch):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute('DROP TABLE operational_events')
        b._db.execute('DROP TABLE operational_control')
        b._db.execute('PRAGMA user_version=2')
    before = capture_database(path)
    connect = sqlite3.connect
    def factory(*args, **kwargs):
        def hook(sql, when):
            if sql.startswith('CREATE TABLE operational_events') and when == 'after':
                raise OSError('migration stage fault')
        return ConnectionProxy(connect(*args, **kwargs), hook)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', factory)
        with pytest.raises(OSError, match='migration stage fault'): PaperBroker(path)
    assert capture_database(path) == before
    with PaperBroker(path) as b:
        assert b.strict and b.get_order('buy').status == 'ACCEPTED' and not b.fills()


def test_critical_check_holds_writer_until_latch_commit_with_waiting_fill(tmp_path, monkeypatch):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        b._db.execute('DELETE FROM gate_attempts')
        accepted(b, 'next', ticker='MSFT', quantity=1)
        req = request(b, 'next', 'waiting-fill')
    ready, start_fill, begin_attempted, checked, release_check, fill_done = (Event() for _ in range(6))
    original = controls.reconcile_snapshot
    def paused(*args, **kwargs):
        value = original(*args, **kwargs)
        if value.status == 'CRITICAL':
            checked.set()
            assert release_check.wait(10)
        return value
    monkeypatch.setattr(controls, 'reconcile_snapshot', paused)
    def fill():
        with PaperBroker(path) as b:
            b._db.set_trace_callback(lambda sql: begin_attempted.set() if sql == 'BEGIN IMMEDIATE' else None)
            ready.set()
            assert start_fill.wait(10)
            result = b.execute_gated(req)
            fill_done.set()
            return result
    def check():
        return controls.reconcile_and_latch(path, report_id='coordinated', timestamp=NOW,
            activation_id='coordinated-block', operator_id='operator', reason='serialized critical inspection')
    with ThreadPoolExecutor(max_workers=2) as pool:
        filling = pool.submit(fill)
        assert ready.wait(10)
        checking = pool.submit(check)
        try:
            assert checked.wait(10)
            # Before even starting the fill contender, prove the coordinated
            # checker still owns a writer reservation after CRITICAL detection.
            with sqlite3.connect(path, timeout=0, isolation_level=None) as probe:
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    probe.execute('BEGIN IMMEDIATE')
            start_fill.set()
            assert begin_attempted.wait(10)
            assert not fill_done.is_set()  # Actual writer attempted, not a timing sleep.
        finally:
            release_check.set()
            start_fill.set()
        result, outcome = checking.result(timeout=15), filling.result(timeout=15)
    assert result.report.status == 'CRITICAL' and result.block_id == 'coordinated-block'
    assert outcome.status == 'REJECTED' and 'OPERATIONAL_BLOCK' in outcome.reasons[0]
    with PaperBroker(path) as b: assert len(b.fills()) == 1


def test_fill_during_recovery_waits_then_rejects_stale_authorization(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute("UPDATE account SET cash='9999'")
    activate(path, report(path))
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    healthy = report(path)
    ready, start_fill, verifying, release_verify, attempted = (Event() for _ in range(5))
    def fill():
        with PaperBroker(path) as b:
            req = request(b)
            b._db.set_trace_callback(lambda sql: attempted.set() if sql == 'BEGIN IMMEDIATE' else None)
            ready.set()
            assert start_fill.wait(10)
            return b.execute_gated(req)
    def authorizer(req, value):
        verifying.set()
        assert release_verify.wait(10)
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        filling = pool.submit(fill)
        assert ready.wait(10)
        releasing = pool.submit(controls.release_operational_block, path, recovery(healthy), healthy, authorize=authorizer)
        try:
            assert verifying.wait(10)
            start_fill.set()
            assert attempted.wait(10)
        finally:
            release_verify.set()
            start_fill.set()
        released, outcome = releasing.result(timeout=15), filling.result(timeout=15)
    assert released['action'] == 'RELEASED'
    assert outcome.status == 'REJECTED' and 'STALE_STATE' in outcome.reasons[0]
    with PaperBroker(path) as b: assert not b.fills() and not b.portfolio().kill_switch


def test_private_accounting_helper_cannot_skip_integrity_preflight(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        with b._transaction():
            b._gate_active = True
            try:
                with pytest.raises(ValueError, match='integrity preflight'):
                    b._simulate_fill_locked('buy', Decimal(100), Decimal(0), Decimal(0), NOW.isoformat())
            finally:
                b._gate_active = False
        assert not b.fills()


def test_kill_writer_waits_for_inflight_fill_then_blocks_pending_execution(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        accepted(b, 'next', ticker='MSFT', quantity=1)
        req = request(b)
    fill_ready, kill_ready, start_fill, start_kill, wrote, release_fill, kill_begin, kill_done = (Event() for _ in range(8))
    def fill():
        with PaperBroker(path) as b:
            def pause(sql, when):
                if sql.startswith('UPDATE account SET cash=') and when == 'after':
                    wrote.set()
                    assert release_fill.wait(10)
            b._db = ConnectionProxy(b._db, pause)
            fill_ready.set()
            assert start_fill.wait(10)
            return b.execute_gated(req)
    def kill():
        with PaperBroker(path) as b:
            b._db.set_trace_callback(lambda sql: kill_begin.set() if sql == 'BEGIN IMMEDIATE' else None)
            kill_ready.set()
            assert start_kill.wait(10)
            b.set_kill_switch(True, timestamp=NOW, reason='concurrent explicit kill')
            kill_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        filling, killing = pool.submit(fill), pool.submit(kill)
        try:
            assert fill_ready.wait(10) and kill_ready.wait(10)
            start_fill.set()
            assert wrote.wait(10)
            start_kill.set()
            assert kill_begin.wait(10) and not kill_done.is_set()
        finally:
            release_fill.set()
            start_fill.set()
            start_kill.set()
        assert filling.result(timeout=15).status == 'FILLED'
        killing.result(timeout=15)
    with PaperBroker(path) as b:
        assert b.portfolio().kill_switch and not report(path).operational_block
        next_outcome = b.execute_gated(request(b, 'next', 'after-kill'))
        assert next_outcome.status == 'REJECTED' and 'KILL_SWITCH' in next_outcome.reasons[0]
        assert b.execute_gated(req).status == 'FILLED' and len(b.fills()) == 1  # Historical read only.
        kinds = [e.event for e in b.audit_events()]
        assert kinds.index('FILLED') < kinds.index('KILL_ENABLED')


def test_concurrent_orders_cannot_spend_conservatively_reserved_limited_cash(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True, initial_cash='1000') as b:
        for i, ticker in enumerate(('JPM', 'XOM', 'JNJ')):
            accepted(b, str(i), ticker=ticker, quantity=2)
            assert b.execute_gated(request(b, str(i), f'seed-{i}')).status == 'FILLED'
        accepted(b, 'a', ticker='AAPL', quantity=2)
        accepted(b, 'm', ticker='MSFT', quantity=2)
        requests = [request(b, i, i) for i in ('a', 'm')]
    barrier = Barrier(2)
    def execute(req):
        with PaperBroker(path) as b:
            barrier.wait(timeout=10)
            return b.execute_gated(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, requests))
    assert all(o.status == 'REJECTED' and 'CASH_RESERVE' in o.reasons[0] for o in outcomes)
    with PaperBroker(path) as b:
        assert b.reconcile().available_cash == 400 and len(b.fills()) == 3


@pytest.mark.parametrize('budget', ['PREFLIGHT_MAX_DATABASE_BYTES', 'PREFLIGHT_MAX_ROWS', 'PREFLIGHT_MAX_GATE_ATTEMPTS'])
def test_preflight_work_budget_refuses_fill_without_claiming_durable_latch(tmp_path, monkeypatch, budget):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        accepted(b, 'next', ticker='MSFT', quantity=1)
        req = request(b, 'next', 'budget-rejected')
        before = b.execution_state()
        monkeypatch.setattr(controls, budget, 0)
        for _ in range(2):
            with pytest.raises(controls.PreflightBudgetExceeded): b.execute_gated(req)
            assert b.execution_state() == before and len(b.fills()) == 1
            assert not report(path).operational_block
        with pytest.raises(KeyError): b.execution_attempt(req.attempt_id)


def test_preflight_cost_profile_on_fixed_synthetic_histories(tmp_path):
    """Reproducible workload, observed timing only: no flaky timing thresholds."""
    points = []
    for history in (0, 8, 24):
        path = tmp_path / f'profile-{history}.sqlite'
        with PaperBroker(path, strict=True) as b:
            for index in range(history):
                identity = f'seed-{index}'
                accepted(b, identity, side='BUY' if index % 2 == 0 else 'SELL', quantity=1)
                assert b.execute_gated(request(b, identity, identity)).status == 'FILLED'
            accepted(b, 'measure', quantity=1)
            req = request(b, 'measure', 'measure')
            timings = []
            for _ in range(3):
                with b._transaction():
                    started = perf_counter()
                    controls.strict_preflight_locked(b, req)
                    timings.append((perf_counter() - started) * 1000)
            assert len(b.fills()) == history  # Measurement never fills its target.
            snapshot = json.loads(capture_database(path).content)
            points.append({'gate_history': history, 'rows': sum(len(rows) for rows in snapshot['tables'].values()),
                'database_bytes': b._db.execute('PRAGMA page_count').fetchone()[0] * b._db.execute('PRAGMA page_size').fetchone()[0],
                'median_preflight_ms': round(median(timings), 3)})
    print('PREFLIGHT_COST_PROFILE=' + json.dumps(points, sort_keys=True))


def test_control_open_failure_preserves_primary_error_and_closes_failed_rollback(tmp_path, monkeypatch):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True): pass
    before = capture_database(path)
    connect = sqlite3.connect
    closed = Event()
    class ClosingProxy(ConnectionProxy):
        def close(self):
            self.inner.close()  # SQLite rolls back the still-uncommitted transaction.
            closed.set()
    def factory(*args, **kwargs):
        def hook(sql, when):
            if when == 'before' and sql == 'SELECT * FROM operational_control':
                raise OSError('primary control read failure')
            if when == 'before' and sql == 'ROLLBACK':
                raise RuntimeError('secondary rollback failure')
        return ClosingProxy(connect(*args, **kwargs), hook)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', factory)
        with pytest.raises(OSError, match='primary control read failure') as caught:
            controls.reconcile_and_latch(path, report_id='failed', timestamp=NOW, activation_id='never-written',
                operator_id='operator', reason='controlled opening failure')
    assert closed.is_set() and any('secondary rollback failure' in note for note in caught.value.__notes__)
    assert capture_database(path) == before
    with PaperBroker(path) as b: assert not b.fills() and not report(path).operational_block


@pytest.mark.parametrize('phase', ['uncommitted_fill', 'committed_response'])
def test_closed_connection_preserves_error_and_resolves_by_original_id(tmp_path, phase):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
        inner = b._db
        fired = False
        def hook(sql, when):
            nonlocal fired
            target = sql.startswith('UPDATE account SET cash=') if phase == 'uncommitted_fill' else sql == 'COMMIT'
            if not fired and when == 'after' and target:
                fired = True
                inner.close()  # Rolls back an active txn; cannot undo a committed one.
                raise OSError('connection lost at controlled boundary')
        b._db = ConnectionProxy(inner, hook)
        with pytest.raises(OSError, match='connection lost') as caught:
            b.execute_gated(req)
        assert fired and caught.value.__notes__
    with PaperBroker(path) as b:
        if phase == 'uncommitted_fill':
            assert not b.fills() and b.get_order('buy').status == 'ACCEPTED'
            with pytest.raises(KeyError): b.execution_attempt(req.attempt_id)
        else:
            assert len(b.fills()) == 1 and b.execution_attempt(req.attempt_id).status == 'FILLED'
        result = b.execute_gated(req)
        assert result.status == 'FILLED' and len(b.fills()) == 1 and b.reconcile().available_cash == 9000
