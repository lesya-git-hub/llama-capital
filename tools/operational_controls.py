"""Explicit sticky operational control actions; never repairs financial records."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from pydantic import AwareDatetime, Field

from tools.fx_conversion import Digest, FXInput
from tools.historical_snapshot import input_hash
from tools.operational_monitoring import (BROKER_APP, MonitoringReport,
    capture_connection, database_identity, replay_report, stable_json)


class RecoveryRequest(FXInput):
    recovery_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    authorization_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    timestamp: AwareDatetime
    report_sha256: Digest


def migrate_strict_controls(db):
    """Called only by broker initialization inside its write transaction."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version == 2:
        existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'operational_control', 'operational_events'} & existing:
            raise ValueError('Inconsistent operational schema; refusing to reset a latch')
        db.execute('CREATE TABLE operational_control (id INTEGER PRIMARY KEY CHECK(id=1), blocked INTEGER NOT NULL CHECK(blocked IN (0,1)), block_id TEXT, report_sha256 TEXT, activated_at TEXT)')
        db.execute('INSERT INTO operational_control VALUES (1,0,NULL,NULL,NULL)')
        db.execute('CREATE TABLE operational_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, request_sha256 TEXT NOT NULL, content_json TEXT NOT NULL, sha256 TEXT NOT NULL)')
        db.execute('PRAGMA user_version=3')
    elif version != 3:
        raise ValueError('Operational controls require a strict schema')
    read_control(db)


def read_control(db):
    rows = db.execute('SELECT * FROM operational_control').fetchall()
    if len(rows) != 1:
        raise ValueError('Missing operational latch; refusing execution')
    row = dict(zip([d[0] for d in db.execute('SELECT * FROM operational_control').description], tuple(rows[0])))
    if (row['id'] != 1 or row['blocked'] not in (0, 1)
            or (bool(row['blocked']) != bool(row['block_id']))):
        raise ValueError('Invalid operational latch; refusing execution')
    if row['blocked'] and (not row['report_sha256'] or not row['activated_at']):
        raise ValueError('Operational latch lacks activation evidence; refusing execution')
    if not row['blocked'] and (row['report_sha256'] is not None or row['activated_at'] is not None):
        raise ValueError('Released latch contains inconsistent activation metadata')
    active = None
    cursor = db.execute('SELECT * FROM operational_events ORDER BY sequence DESC')
    names = [d[0] for d in cursor.description]
    for event in cursor:
        values = dict(zip(names, tuple(event)))
        if sha256(values['content_json'].encode()).hexdigest() != values['sha256']:
            raise ValueError('Operational audit integrity mismatch; refusing execution')
        payload = json.loads(values['content_json'])
        if payload['event_id'] != values['event_id']:
            raise ValueError('Operational event identity conflict; refusing execution')
        if payload['action'] == 'ACTIVATED':
            active = payload['block_id']
            if row['report_sha256'] != payload['report_sha256'] or row['activated_at'] != payload['timestamp']:
                raise ValueError('Operational activation metadata conflict; refusing execution')
            break
        if payload['action'] == 'RELEASED':
            break
        if payload['action'] != 'DENIED':
            raise ValueError('Invalid operational event; refusing execution')
    if bool(row['blocked']) != (active is not None) or row['block_id'] != active:
        raise ValueError('Operational control/audit conflict; refusing execution')
    return row


def _open(path):
    # mode=rw never initializes a missing/corrupt ledger or calls broker startup
    # reconciliation, so an existing corrupted financial state can be latched.
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA application_id').fetchone()[0] != BROKER_APP or db.execute('PRAGMA user_version').fetchone()[0] != 3:
            raise ValueError('Operational control action requires an initialized strict version-3 ledger')
        if db.execute('SELECT mode FROM execution_mode WHERE id=1').fetchone()[0] != 'strict_synthetic':
            raise ValueError('Invalid strict mode')
        read_control(db)
        return db
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        db.close()
        raise


def _prior(db, event_id, request_sha256):
    row = db.execute('SELECT * FROM operational_events WHERE event_id=?', (event_id,)).fetchone()
    if row is None: return None
    if row['request_sha256'] != request_sha256:
        raise ValueError('Conflicting operational action identity')
    if sha256(row['content_json'].encode()).hexdigest() != row['sha256']:
        raise ValueError('Operational audit integrity mismatch')
    return json.loads(row['content_json'])


def _append(db, event, request_sha256):
    content = stable_json(event)
    db.execute('INSERT INTO operational_events(event_id,request_sha256,content_json,sha256) VALUES (?,?,?,?)',
        (event['event_id'], request_sha256, content, sha256(content.encode()).hexdigest()))


def _validate_current(db, path, report, expected_sha256):
    report = replay_report(report, expected_sha256=expected_sha256)
    if report.snapshot.broker.identity != database_identity(path):
        raise ValueError('Operational report targets a different ledger')
    current = capture_connection(db, database_identity(path))
    if current != report.snapshot.broker:
        raise ValueError('Stale monitoring snapshot; capture and investigate current state')
    # Journal snapshots are frozen evidence, not atomically locked live sidecars.
    # The trusted recovery authorizer must assess any cross-file limitations.
    return report


def activate_operational_block(path, report, *, expected_sha256, activation_id, operator_id, reason, timestamp):
    if not all(isinstance(v, str) and v.strip() for v in (activation_id, operator_id, reason)):
        raise ValueError('Explicit action identity, operator and reason required')
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Explicit aware action timestamp required')
    report = MonitoringReport.model_validate(report.model_dump(mode='json'))
    request = {'action': 'ACTIVATED', 'event_id': activation_id, 'operator_id': operator_id, 'reason': reason,
        'timestamp': timestamp.astimezone(timezone.utc).isoformat(), 'report_sha256': expected_sha256}
    digest = sha256(stable_json(request).encode()).hexdigest()
    db = _open(path)
    try:
        prior = _prior(db, activation_id, digest)
        if prior is not None:
            db.execute('COMMIT')
            return prior
        report = _validate_current(db, path, report, expected_sha256)
        if report.status != 'CRITICAL' or timestamp < report.reported_at:
            raise ValueError('A current critical report and causal action timestamp are required')
        if read_control(db)['blocked']:
            raise ValueError('Already operationally blocked; original evidence is preserved')
        event = request | {'block_id': activation_id, 'snapshot_sha256': report.snapshot_sha256,
            'findings': [f.model_dump(mode='json') for f in report.findings],
            'control_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}
        db.execute('UPDATE operational_control SET blocked=1,block_id=?,report_sha256=?,activated_at=? WHERE id=1',
                   (activation_id, expected_sha256, request['timestamp']))
        _append(db, event, digest)
        db.execute('COMMIT')
        return event
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise
    finally:
        db.close()


def release_operational_block(path, request, report, *, authorize=None):
    """authorize is a TRUSTED LOCAL application verifier, not request data.

    It must independently verify the operator/authorization and block/report
    scope. No verifier means denial. This library does not authenticate identities.
    """
    request = RecoveryRequest.model_validate(request.model_dump(mode='json'))
    digest = input_hash(request)
    db = _open(path)
    denied = None
    try:
        prior = _prior(db, request.recovery_id, digest)
        if prior is not None:
            db.execute('COMMIT')
            if prior['action'] == 'DENIED': raise PermissionError(prior['denial'])
            return prior
        control = read_control(db)
        report = _validate_current(db, path, report, request.report_sha256)
        if not control['blocked'] or control['block_id'] != request.block_id:
            raise ValueError('Recovery must name the current active block')
        if request.timestamp < report.reported_at or request.timestamp < datetime.fromisoformat(control['activated_at']):
            raise ValueError('Recovery timestamp violates control/report chronology')
        if report.status == 'CRITICAL' or not report.financial_reconstruction_complete:
            denied = 'Recovery requires complete reconstruction with no critical findings'
        elif not callable(authorize):
            denied = 'An independent trusted operator authorizer is required'
        else:
            try:
                if authorize(request, report) is not True:
                    denied = 'Operator authorization was denied'
            except Exception:
                denied = 'Operator authorization verification failed'
        event = {'event_id': request.recovery_id, 'action': 'DENIED' if denied else 'RELEASED',
            'block_id': request.block_id, 'operator_id': request.operator_id,
            'authorization_id': request.authorization_id, 'reason': request.reason,
            'timestamp': request.timestamp.isoformat(), 'report_sha256': request.report_sha256,
            'snapshot_sha256': report.snapshot_sha256, 'denial': denied,
            'control_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'findings': [f.model_dump(mode='json') for f in report.findings]}
        if not denied:
            db.execute('UPDATE operational_control SET blocked=0,block_id=NULL,report_sha256=NULL,activated_at=NULL WHERE id=1')
        _append(db, event, digest)
        db.execute('COMMIT')
        if denied: raise PermissionError(denied)
        return event
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise
    finally:
        db.close()
