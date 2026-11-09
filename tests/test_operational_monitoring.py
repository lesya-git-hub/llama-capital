from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import sqlite3
from threading import Barrier

import pytest

from providers.paper_broker import PaperBroker
from tools.gated_execution import LedgerState
from tools.historical_snapshot import canonical_json, input_hash
from tools.operational_monitoring import (MonitoringPolicy, capture_operational_state, monitor,
    reconcile_snapshot, replay_report, human_report)
from tools.operational_controls import (RecoveryRequest, activate_operational_block, release_operational_block)
from tests.test_gated_execution import accepted, request, NOW
from tests.test_market_verification import fixture
from tests.test_paper_orchestration import signals


def report(path, identity='daily', workflows=()):
    return monitor(path, report_id=identity, reported_at=NOW, workflow_paths=workflows)


def codes(value):
    return {f.code for f in value.findings}


def activate(path, value, identity='critical'):
    return activate_operational_block(path, value, expected_sha256=input_hash(value), activation_id=identity,
        operator_id='monitor-operator', reason='Investigated synthetic finding', timestamp=NOW)


def recovery(value, identity='recovery', operator='approved', block='critical'):
    return RecoveryRequest(recovery_id=identity, block_id=block, operator_id=operator,
        authorization_id='independent-test-approval', reason='Synthetic investigation completed', timestamp=NOW,
        report_sha256=input_hash(value))


@pytest.mark.parametrize('strict', [False, True])
def test_empty_healthy_read_only_and_stable_replay(tmp_path, strict, monkeypatch):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=strict): pass
    before = path.read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('Reports cannot execute or use external transport')
    import socket
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(PaperBroker, 'execute_gated', forbidden)
    monkeypatch.setattr(PaperBroker, 'simulate_fill', forbidden)
    first = report(path)
    with localcontext() as context:
        context.prec = 3
        second = report(path)
    assert first.status == 'HEALTHY' and first.cash_eur == 10000
    assert first == second and input_hash(first) == input_hash(second)
    assert first.financial_reconstruction_complete and first.evidence_complete
    assert replay_report(first, expected_sha256=input_hash(first)) == first
    assert before == path.read_bytes()
    assert 'investment-performance' in human_report(first)


def test_healthy_buy_partial_sell_and_independent_cost_rounding(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b, quantity=10)
        assert b.execute_gated(request(b, proposal_changes={'commission': '1', 'slippage': '.1'})).status == 'FILLED'
        accepted(b, 'sell', side='SELL', quantity=3)
        assert b.execute_gated(request(b, 'sell', 'sale')).status == 'FILLED'
    result = report(path)
    assert result.status == 'HEALTHY', result.findings
    rebuilt = json.loads(result.reconstructed_json)
    assert rebuilt['positions']['AAPL']['quantity'] == 7
    assert Decimal(rebuilt['cash_eur']) == Decimal('9298')
    assert Decimal(rebuilt['positions']['AAPL']['cost_basis_eur']) == Decimal('701.4')
    assert Decimal(rebuilt['realized_pnl_eur']) == Decimal('-.6')


@pytest.mark.parametrize('mutation,code', [
    ("UPDATE account SET cash='9001'", 'CASH_MISMATCH'),
    ("UPDATE positions SET quantity=11", 'HOLDINGS_MISMATCH'),
    ("UPDATE positions SET cost_basis='1001'", 'COST_BASIS_MISMATCH'),
    ("UPDATE account SET realized_pnl='1'", 'REALIZED_PNL_MISMATCH'),
    ("UPDATE fills SET commission='1'", 'FILL_ARITHMETIC_MISMATCH'),
    ("DELETE FROM gate_attempts", 'STRICT_FILL_WITHOUT_GATE'),
    ("UPDATE orders SET status='CANCELLED'", 'ORDER_STATUS_CONFLICT'),
])
def test_independent_financial_and_authority_mismatches(tmp_path, mutation, code):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        b._db.execute(mutation)
    value = report(path)
    assert value.status == 'CRITICAL' and code in codes(value)
    assert report(path) == value  # No repairs, including when normal startup fails.


def test_duplicate_fill_and_missing_lifecycle_evidence(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path) as b:
        accepted(b)
        b.simulate_fill('buy', price='100', timestamp=NOW)
        b._db.execute("INSERT INTO audit(order_id,event,timestamp,reason) VALUES ('buy','FILLED',?,'corrupt duplicate')", (NOW.isoformat(),))
    value = report(path)
    assert value.status == 'CRITICAL' and 'DUPLICATE_FILL' in codes(value)
    assert not value.financial_reconstruction_complete


def test_corrupted_rejection_audit_is_critical(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b, quantity=21)
        outcome = b.execute_gated(request(b))
        changed = json.loads(outcome.after.content)
        changed['account'][0]['cash'] = '1'
        altered = outcome.model_copy(update={'after': LedgerState(content=json.dumps(changed))})
        b._db.execute('UPDATE gate_attempts SET record_json=?,record_sha256=?', (canonical_json(altered), input_hash(altered)))
    value = report(path)
    assert value.status == 'CRITICAL' and 'REJECTION_STATE_MUTATION' in codes(value)


def test_safe_v2_migration_preserves_all_original_rows(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        b._db.execute('DROP TABLE operational_events')
        b._db.execute('DROP TABLE operational_control')
        b._db.execute('PRAGMA user_version=2')
        original = {name: b._db.execute(f'SELECT * FROM {name}').fetchall() for name in
                    ('account', 'orders', 'fills', 'positions', 'audit', 'execution_mode', 'gate_attempts', 'gate_holdings', 'gate_order_terms')}
        original = {k: [tuple(r) for r in rows] for k, rows in original.items()}
    with PaperBroker(path) as b:
        assert b.strict and b._db.execute('PRAGMA user_version').fetchone()[0] == 3
        for name, rows in original.items(): assert [tuple(r) for r in b._db.execute(f'SELECT * FROM {name}')] == rows
        assert b._db.execute('SELECT blocked FROM operational_control').fetchone()[0] == 0


def test_block_corrupt_ledger_then_persist_after_repair_restart_and_healthy_report(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute("UPDATE account SET cash='9999'")
    critical = report(path)
    with pytest.raises(ValueError): PaperBroker(path)
    event = activate(path, critical)
    assert event['action'] == 'ACTIVATED' and event['findings']
    assert activate(path, critical) == event  # Read-only exact control retry.
    # Explicit synthetic fixture correction; no report/control API repairs data.
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    healthy = report(path)
    assert healthy.status == 'HEALTHY' and healthy.operational_block is True
    with PaperBroker(path) as b:
        assert b.execute_gated(request(b)).status == 'REJECTED'
        b.set_kill_switch(True, timestamp=NOW, reason='independent switch')
        b.set_kill_switch(False, timestamp=NOW, reason='must not clear latch')
        outcome = b.execute_gated(request(b, attempt='after-kill-clear'))
        assert 'OPERATIONAL_BLOCK' in outcome.reasons[0] and not b.fills()


def test_explicit_authorized_recovery_and_independent_kill(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute("UPDATE account SET cash='9999'")
    activate(path, report(path))
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    healthy = report(path)
    with pytest.raises(PermissionError): release_operational_block(path, recovery(healthy), healthy)
    assert report(path).operational_block is True
    healthy = report(path)
    with pytest.raises(PermissionError):
        release_operational_block(path, recovery(healthy, 'bad', 'unauthorized'), healthy,
                                   authorize=lambda request, report: request.operator_id == 'approved')
    with PaperBroker(path) as b: b.set_kill_switch(True, timestamp=NOW, reason='keep kill active')
    healthy = report(path)
    request_recovery = recovery(healthy, 'approved-recovery')
    event = release_operational_block(path, request_recovery, healthy, authorize=lambda req, report: req.operator_id == 'approved')
    assert event['action'] == 'RELEASED'
    assert release_operational_block(path, request_recovery, healthy) == event  # Historical retry, no new release.
    with PaperBroker(path) as b:
        value = report(path)
        assert value.operational_block is False and value.kill_switch is True
        outcome = b.execute_gated(request(b))
        assert outcome.status == 'REJECTED' and 'KILL_SWITCH' in outcome.reasons[0]
        assert not b.fills()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM operational_events").fetchone()[0] == 4


def test_detection_activation_race_and_concurrent_fill(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b.execute_gated(request(b))
        b._db.execute('DELETE FROM gate_attempts')  # Critical but financially consistent.
        accepted(b, 'next', ticker='MSFT', quantity=1)
        req = request(b, 'next', 'next-attempt')
    critical = report(path)
    barrier = Barrier(2)
    def fill():
        with PaperBroker(path) as b:
            barrier.wait()
            return b.execute_gated(req)
    def block():
        barrier.wait()
        try: return activate(path, critical)
        except ValueError as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f, c = pool.submit(fill), pool.submit(block)
        result, control = f.result(timeout=20), c.result(timeout=20)
    if isinstance(control, dict):
        assert result.status == 'REJECTED' and 'OPERATIONAL_BLOCK' in result.reasons[0]
    else:
        assert result.status == 'FILLED' and 'Stale' in control  # Documented pre-activation race window.
        activate(path, report(path), 'fresh-critical')
    assert report(path).operational_block is True


def test_concurrent_recovery_is_state_bound(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b: b._db.execute("UPDATE account SET cash='9999'")
    activate(path, report(path))
    with sqlite3.connect(path) as db: db.execute("UPDATE account SET cash='10000'")
    healthy = report(path)
    barrier = Barrier(2)
    def release(identity):
        barrier.wait()
        try: return release_operational_block(path, recovery(healthy, identity), healthy, authorize=lambda req, report: True)
        except ValueError as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(release, ('one', 'two')))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert report(path).operational_block is False


def test_control_audit_failure_rolls_back_latch_and_refuses_silent_downgrade(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        b._db.execute("UPDATE account SET cash='9999'")
        b._db.execute("CREATE TRIGGER fail_control BEFORE INSERT ON operational_events BEGIN SELECT RAISE(ABORT,'control audit fault'); END")
    critical = report(path)
    with pytest.raises(sqlite3.IntegrityError): activate(path, critical)
    assert report(path).operational_block is False
    with sqlite3.connect(path) as db:
        db.execute('DROP TRIGGER fail_control')
        db.execute('PRAGMA user_version=2')
        db.execute("UPDATE account SET cash='10000'")
    assert 'OPERATIONAL_SCHEMA_CONFLICT' in codes(report(path))
    with pytest.raises(ValueError, match='refusing to reset'): PaperBroker(path)


def test_missing_or_unreadable_database_is_critical_without_creation(tmp_path):
    path = tmp_path / 'missing.sqlite'
    assert report(path).status == 'CRITICAL' and not path.exists()
    path.write_bytes(b'not a database')
    before = path.read_bytes()
    assert report(path).status == 'CRITICAL' and before == path.read_bytes()


def test_raw_duplicate_fill_and_missing_uniqueness_are_critical(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path) as b:
        accepted(b)
        b.simulate_fill('buy', price='100', timestamp=NOW)
        b._db.execute('CREATE TABLE duplicate_fills AS SELECT * FROM fills UNION ALL SELECT * FROM fills')
        b._db.execute('DROP TABLE fills')
        b._db.execute('ALTER TABLE duplicate_fills RENAME TO fills')
    value = report(path)
    assert {'DUPLICATE_FILL', 'SCHEMA_CONSTRAINT_MISSING'} <= codes(value)
    assert value.status == 'CRITICAL' and not value.financial_reconstruction_complete


def test_proven_fill_while_killed_is_critical(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path) as b:
        accepted(b)
        b.simulate_fill('buy', price='100', timestamp=NOW)
        b._db.execute("UPDATE audit SET sequence=4 WHERE event='FILLED'")
        b._db.execute("INSERT INTO audit(sequence,order_id,event,timestamp,reason) VALUES (3,NULL,'KILL_ENABLED',?,'synthetic conflict')", (NOW.isoformat(),))
        b._db.execute('UPDATE account SET killed=1')
    value = report(path)
    assert value.status == 'CRITICAL' and 'FILL_WHILE_KILLED' in codes(value)


def test_workflow_health_and_operational_block_cannot_be_bypassed(tmp_path, signals):
    from tests.test_paper_orchestration import prepare, plan, proposal, staged, authorize
    from tools.paper_orchestration import preview_workflow, execute_workflow
    b, store, p = prepare(tmp_path, signals)
    path = tmp_path / 'broker.sqlite'
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        value = report(path, workflows=(store.path,))
        assert value.status == 'HEALTHY', value.findings
        with sqlite3.connect(store.path) as journal:
            original_sha = journal.execute('SELECT request_sha256 FROM steps').fetchone()[0]
            journal.execute('UPDATE steps SET request_sha256=?', ('0' * 64,))
        conflict = report(path, workflows=(store.path,))
        assert conflict.status == 'CRITICAL' and 'WORKFLOW_AUDIT_CONFLICT' in codes(conflict)
        with sqlite3.connect(store.path) as journal:
            journal.execute('UPDATE steps SET request_sha256=?', (original_sha,))
        staged(b, signals[-1], 'm', 'MSFT')
        next_plan = plan(b, signals, (proposal('m', 'MSFT'),), run='blocked-workflow')
        next_preview = preview_workflow(next_plan, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        b._db.execute("UPDATE positions SET cost_basis='1001'")
        critical = report(path, workflows=(store.path,))
        activate(path, critical)
        outcome = execute_workflow(next_plan.run_id, authorization=authorize(next_preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert outcome.steps[0].status == 'REJECTED'
        assert 'OPERATIONAL_BLOCK' in outcome.steps[0].reasons[0]
        assert len(b.fills()) == 1


def test_workflow_commit_gap_is_warning_and_monitor_never_resumes_it(tmp_path, signals, monkeypatch):
    from tests.test_paper_orchestration import prepare, authorize
    from tools.paper_orchestration import preview_workflow, execute_workflow
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        original = store._step
        def interrupt(run_id, req, outcome=None):
            if outcome is not None: raise KeyboardInterrupt('synthetic post-commit gap')
            return original(run_id, req, outcome)
        monkeypatch.setattr(store, '_step', interrupt)
        auth = authorize(preview, signals[-1])
        with pytest.raises(KeyboardInterrupt): execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        value = report(tmp_path / 'broker.sqlite', workflows=(store.path,))
        assert value.status == 'WARNING' and 'WORKFLOW_COMMIT_GAP' in codes(value)
        assert len(b.fills()) == 1
        monkeypatch.setattr(store, '_step', original)
        execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        assert report(tmp_path / 'broker.sqlite', workflows=(store.path,)).status == 'HEALTHY'


def test_partial_workflow_is_reported_as_recoverable_warning(tmp_path, signals):
    from tests.test_paper_orchestration import prepare, proposal, authorize
    from tools.paper_orchestration import preview_workflow, execute_workflow
    b, store, p = prepare(tmp_path, signals, (proposal(), proposal('m', 'MSFT')))
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        b._db.execute("CREATE TRIGGER second_fault BEFORE INSERT ON fills WHEN NEW.order_id='m' BEGIN SELECT RAISE(ABORT,'synthetic second fault'); END")
        outcome = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert outcome.status == 'PARTIAL'
        value = report(tmp_path / 'broker.sqlite', workflows=(store.path,))
        assert value.status == 'WARNING' and 'PARTIAL_WORKFLOW' in codes(value)


def test_all_strict_fill_paths_check_persisted_latch(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        b._db.execute("UPDATE account SET cash='9999'")
        activate(path, report(path))
        b._db.execute("UPDATE account SET cash='10000'")
        with pytest.raises(ValueError, match='direct manual'):
            b.simulate_fill('buy', price='100', timestamp=NOW)
        with b._transaction():
            b._gate_active = True  # Exercise helper guard independently of gate.
            try:
                with pytest.raises(ValueError, match='Operational latch'):
                    b._simulate_fill_locked('buy', Decimal(100), Decimal(0), Decimal(0), NOW.isoformat())
            finally:
                b._gate_active = False
        assert not b.fills() and b.portfolio().available_cash == 10000


def test_control_metadata_conflict_is_critical_and_fails_closed(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        b._db.execute("UPDATE account SET cash='9999'")
    activate(path, report(path))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE account SET cash='10000'")
        db.execute('UPDATE operational_control SET report_sha256=?', ('0' * 64,))
    value = report(path)
    assert value.status == 'CRITICAL' and 'OPERATIONAL_STATE_CONFLICT' in codes(value)
    with pytest.raises(ValueError, match='metadata conflict'): PaperBroker(path)


def test_missing_operational_audit_table_is_critical_even_when_unblocked(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path, strict=True) as b:
        b._db.execute('DROP TABLE operational_events')
    value = report(path)
    assert value.status == 'CRITICAL' and 'MISSING_OPERATIONAL_AUTHORITY' in codes(value)
    with pytest.raises(sqlite3.OperationalError): PaperBroker(path)
