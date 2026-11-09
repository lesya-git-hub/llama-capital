"""Explicit offline SQLite backup and inspection-only disaster recovery.

Bundles are sealed by hashes, not authenticated. Publication uses Windows'
no-replace directory rename. No scheduler, overwrite, or quarantine release.
"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from tools.operational_monitoring import (
    BROKER_APP, MonitoringPolicy, MonitoringReport, OperationalSnapshot, capture_connection,
    reconcile_snapshot, stable_json,
)
from tools.restore_quarantine import install_restore_fence, read_restore_fence
from tools.historical_snapshot import input_hash

MAX_BYTES = 64 * 1024 * 1024
MAX_STEPS = 4096
MAX_SECONDS = 30
WARNINGS = {'REPLAY_ENVIRONMENT_UNAVAILABLE', 'WORKFLOW_SCOPE_NOT_INSPECTED'}
JOURNAL_APP = 0x4C4C524A


def _hash(data):
    return sha256(data).hexdigest()


def _canonical(value):
    return stable_json(value).encode('utf-8')


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}', value):
        raise ValueError('Explicit filesystem-safe identity required')
    return value


def _stamp(timestamp):
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Explicit aware timestamp required')
    return timestamp.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _path(value):
    path = Path(value).absolute()
    # Do not follow links/reparse points into another publication namespace.
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Symlink/junction paths are unsupported')
    return path.resolve()


def _ro(path):
    db = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=2)
    db.execute('PRAGMA query_only=ON')
    return db


def _write(path, data):
    with open(path, 'xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _publish(stage, target):
    if os.name != 'nt':
        raise RuntimeError('No-clobber directory publication currently supports Windows only')
    if stage.parent != target.parent:
        raise ValueError('Publication must remain on the same filesystem and parent')
    # Windows rename refuses an existing file OR directory, including a racing
    # creator. Never replace(), even if an earlier existence check was false.
    os.rename(stage, target)


def _copy_online(source, destination):
    start = time.monotonic()
    calls = 0
    page_size = 65536

    def progress(status, remaining, total):
        nonlocal calls
        calls += 1
        if calls > MAX_STEPS or time.monotonic() - start > MAX_SECONDS or total * page_size > MAX_BYTES:
            raise ValueError('Online backup resource budget exceeded')

    with closing(_ro(source)) as src, closing(sqlite3.connect(destination, isolation_level=None)) as dst:
        page_size = src.execute('PRAGMA page_size').fetchone()[0]
        if src.execute('PRAGMA page_count').fetchone()[0] * page_size > MAX_BYTES:
            raise ValueError('Backup size budget exceeded')
        src.backup(dst, pages=128, progress=progress, sleep=0.01)
        # Destination only: make the completed image independent of WAL files.
        dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        if dst.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
            raise ValueError('Backup image could not be made self-contained')
    if destination.stat().st_size > MAX_BYTES:
        raise ValueError('Backup size budget exceeded')
    with open(destination, 'r+b') as stream:
        os.fsync(stream.fileno())


def _inspect(path, *, identity, artifact_id, timestamp, policy):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Verification size budget exceeded')
    with closing(_ro(path)) as db:
        db.execute('BEGIN')
        # Prevent accidental work on unknown application/schema identities.
        if db.execute('PRAGMA application_id').fetchone()[0] != BROKER_APP or db.execute('PRAGMA user_version').fetchone()[0] not in (1, 3, 4):
            raise ValueError('Unsupported backup application/schema')
        read_restore_fence(db)
        snapshot = capture_connection(db, identity)
        db.execute('ROLLBACK')
    raw = json.loads(snapshot.content)
    row_count = sum(len(rows) for rows in raw['tables'].values())
    if row_count > 10000:
        raise ValueError('Verification row budget exceeded')
    report = reconcile_snapshot(OperationalSnapshot(broker=snapshot), report_id=artifact_id,
        reported_at=datetime.fromisoformat(timestamp), policy=MonitoringPolicy.model_validate(policy))
    if (not report.financial_reconstruction_complete or
            any(f.severity == 'CRITICAL' or f.code not in WARNINGS for f in report.findings)):
        raise ValueError('Backup financial/audit verification failed: ' + ','.join(f.code for f in report.findings))
    facts = dict(application_id=raw['application_id'], schema_version=raw['user_version'],
        logical_sha256=_hash(snapshot.content.encode()),
        counts={name: len(rows) for name, rows in raw['tables'].items()},
        kill_switch=report.kill_switch, operational_block=report.operational_block,
        restore_quarantined=raw['user_version'] == 4)
    return facts, report.model_dump(mode='json')


def _seal(stage, *, kind, artifact_id, source_identity, timestamp, policy, extra=None):
    facts, report = _inspect(stage / 'ledger.sqlite', identity=source_identity,
        artifact_id=artifact_id, timestamp=timestamp, policy=policy)
    evidence = _canonical(report)
    _write(stage / 'verification.json', evidence)
    image = (stage / 'ledger.sqlite').read_bytes()
    manifest = dict(format_version=1, kind=kind, artifact_id=artifact_id,
        source_identity=source_identity, created_at=timestamp, policy=policy,
        database_sha256=_hash(image), database_bytes=len(image),
        verification_sha256=_hash(evidence), facts=facts,
        scope='broker-only; historical replay may require archived code; hashes are not authenticity',
        extra=extra or {})
    data = _canonical(manifest)
    _write(stage / 'manifest.json', data)
    return _hash(data)


def verify_bundle(bundle, *, expected_manifest_sha256):
    """Read-only verification requiring an independently retained manifest hash."""
    path = _path(bundle)
    if not path.is_dir() or path.name.startswith('.partial-'):
        raise ValueError('No published bundle')
    if {p.name for p in path.iterdir()} != {'ledger.sqlite', 'verification.json', 'manifest.json'}:
        raise ValueError('Incomplete or unexpected bundle files')
    for item in path.iterdir():
        if _path(item) != item or not item.is_file():
            raise ValueError('Invalid bundle member')
    if any(p.stat().st_size > MAX_BYTES for p in path.iterdir()):
        raise ValueError('Bundle file size budget exceeded')
    data = (path / 'manifest.json').read_bytes()
    if len(data) > MAX_BYTES or _hash(data) != expected_manifest_sha256:
        raise ValueError('Manifest hash mismatch')
    manifest = json.loads(data)
    if (manifest.get('format_version') != 1 or manifest.get('kind') not in ('backup', 'restore')
            or _canonical(manifest) != data or manifest.get('artifact_id') != path.name):
        raise ValueError('Manifest identity/format mismatch')
    image = path / 'ledger.sqlite'
    if image.stat().st_size != manifest['database_bytes'] or image.stat().st_size > MAX_BYTES or _hash(image.read_bytes()) != manifest['database_sha256']:
        raise ValueError('Database content hash mismatch')
    evidence_bytes = (path / 'verification.json').read_bytes()
    if _hash(evidence_bytes) != manifest['verification_sha256']:
        raise ValueError('Verification evidence hash mismatch')
    evidence = json.loads(evidence_bytes)
    recorded = MonitoringReport.model_validate(evidence)
    if input_hash(recorded.snapshot) != recorded.snapshot_sha256:
        raise ValueError('Verification snapshot hash mismatch')
    if (evidence.get('report_id') != manifest['artifact_id'] or
            evidence['policy'] != manifest['policy'] or
            datetime.fromisoformat(evidence['reported_at']) != datetime.fromisoformat(manifest['created_at']) or
            evidence.get('snapshot', {}).get('broker', {}).get('identity') != manifest['source_identity'] or
            not evidence.get('financial_reconstruction_complete') or
            any(f['severity'] == 'CRITICAL' or f['code'] not in WARNINGS for f in evidence.get('findings', []))):
        raise ValueError('Inconsistent verification evidence')
    facts, report = _inspect(image, identity=manifest['source_identity'], artifact_id=manifest['artifact_id'],
        timestamp=manifest['created_at'], policy=manifest['policy'])
    if facts != manifest['facts'] or evidence['snapshot']['broker']['content'] != report['snapshot']['broker']['content']:
        raise ValueError('Manifest/image verification conflict')
    for key in ('cash_eur', 'holdings_json', 'order_counts_json', 'gate_counts_json',
                'reconstructed_json', 'strict', 'kill_switch', 'operational_block'):
        if evidence[key] != report[key]:
            raise ValueError('Financial verification evidence conflict: ' + key)
    if manifest['kind'] == 'restore':
        with closing(_ro(image)) as db:
            fence = read_restore_fence(db)
        if fence is None or json.loads(fence['receipt_json']) != manifest['extra']:
            raise ValueError('Restore receipt conflict')
    return manifest


def create_backup(source, root, *, backup_id, timestamp, policy=MonitoringPolicy()):
    """Create a new immutable-by-API bundle; never overwrite or reuse an ID."""
    identity = _identity(backup_id)
    stamp = _stamp(timestamp)
    source, root = _path(source), _path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / identity
    if target.exists():
        raise FileExistsError(target)
    stage = root / ('.partial-' + uuid4().hex)
    stage.mkdir()
    _copy_online(source, stage / 'ledger.sqlite')
    digest = _seal(stage, kind='backup', artifact_id=identity, source_identity=str(source),
        timestamp=stamp, policy=policy.model_dump(mode='json'))
    _publish(stage, target)
    verify_bundle(target, expected_manifest_sha256=digest)
    return dict(path=str(target), manifest_sha256=digest)


def _journal_event(journal, request, action, detail):
    """Each audit event commits separately; failure never implies restore success."""
    path = _path(journal)
    with closing(sqlite3.connect(path, isolation_level=None, timeout=2)) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        app = db.execute('PRAGMA application_id').fetchone()[0]
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables and app == 0 and version == 0:
            db.execute('CREATE TABLE restore_events (sequence INTEGER PRIMARY KEY, restore_id TEXT NOT NULL, request_sha256 TEXT NOT NULL, action TEXT NOT NULL, record_json TEXT NOT NULL, sha256 TEXT NOT NULL)')
            db.execute(f'PRAGMA application_id={JOURNAL_APP}')
            db.execute('PRAGMA user_version=1')
        elif app != JOURNAL_APP or version != 1:
            raise ValueError('Incompatible restore journal')
        request_hash = _hash(_canonical(request))
        for row in db.execute('SELECT request_sha256,record_json,sha256,action FROM restore_events WHERE restore_id=?', (request['restore_id'],)):
            if (row[0] != request_hash or _hash(row[1].encode()) != row[2]
                    or json.loads(row[1])['request'] != request or json.loads(row[1])['action'] != row[3]):
                raise ValueError('Conflicting restore identity or audit integrity')
        record = _canonical(dict(request=request, action=action, detail=detail)).decode()
        db.execute('INSERT INTO restore_events (restore_id,request_sha256,action,record_json,sha256) VALUES (?,?,?,?,?)',
            (request['restore_id'], request_hash, action, record, _hash(record.encode())))
        db.execute('COMMIT')


def _sealed_hash(journal, identity):
    with closing(_ro(journal)) as db:
        rows = db.execute("SELECT record_json,sha256 FROM restore_events WHERE restore_id=? AND action='SEALED' ORDER BY sequence DESC", (identity,)).fetchall()
    if not rows or _hash(rows[0][0].encode()) != rows[0][1]:
        raise ValueError('Missing durable sealed-publication evidence')
    return json.loads(rows[0][0])['detail']['manifest_sha256']


def restore_backup(bundle, target, *, expected_manifest_sha256, journal, restore_id,
                   operator_id, authorization_id, reason, timestamp, authorize):
    """Restore strict v3 to a NEW bundle, always quarantined. No release API.

    authorize receives the exact immutable request copy and must return True.
    A retry can finish auditing an already-published matching copy; never refills.
    """
    identity = _identity(restore_id)
    target, bundle, journal = _path(target), _path(bundle), _path(journal)
    if target.name != identity:
        raise ValueError('Target bundle name must equal restore identity')
    if journal == target or journal.is_relative_to(target) or journal.is_relative_to(bundle):
        raise ValueError('Journal must be independent of source and destination bundles')
    for text in (operator_id, authorization_id, reason):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Explicit operator, authorization and reason required')
    request = dict(restore_id=identity, target=str(target), backup_manifest_sha256=expected_manifest_sha256,
        operator_id=operator_id, authorization_id=authorization_id, reason=reason, timestamp=_stamp(timestamp))
    # Journal initialization itself refuses existing ledgers; no destructive reuse.
    try:
        authorized = callable(authorize) and authorize(dict(request)) is True
    except Exception as exc:
        try:
            _journal_event(journal, request, 'DENIED', 'Authorization callback failed: ' + type(exc).__name__)
        except Exception as audit_error:
            exc.add_note('Authorization failure audit also failed: ' + repr(audit_error))
        raise
    if not authorized:
        _journal_event(journal, request, 'DENIED', 'Authorization refused')
        raise PermissionError('Independent restore authorization required')
    _journal_event(journal, request, 'PREPARED', 'Authorized inspection-only restore requested')
    try:
        manifest = verify_bundle(bundle, expected_manifest_sha256=expected_manifest_sha256)
        if manifest['kind'] != 'backup' or manifest['facts']['schema_version'] != 3:
            raise ValueError('Restore supports verified strict version-3 backups only')
        receipt = request | dict(request_sha256=_hash(_canonical(request)), policy='quarantined_no_release_v1')
        if target.exists():
            # Crash after publication before final journal commit: validate the
            # complete same-request artifact, then record its publication only.
            digest = _sealed_hash(journal, identity)
            restored = verify_bundle(target, expected_manifest_sha256=digest)
            if restored['kind'] != 'restore' or restored['extra'] != receipt:
                raise FileExistsError('Existing destination is not this restore')
        else:
            if not target.parent.is_dir():
                raise ValueError('Destination parent must already exist')
            stage = target.parent / ('.partial-' + uuid4().hex)
            stage.mkdir()
            _copy_online(bundle / 'ledger.sqlite', stage / 'ledger.sqlite')
            # Recheck copied bytes before migration; never trust a source that
            # changed between verification and SQLite's consistent copy.
            if _hash((stage / 'ledger.sqlite').read_bytes()) != manifest['database_sha256']:
                raise ValueError('Source changed during restore')
            with closing(sqlite3.connect(stage / 'ledger.sqlite', isolation_level=None)) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                install_restore_fence(db, _canonical(receipt).decode())
                db.execute('COMMIT')
            with open(stage / 'ledger.sqlite', 'r+b') as stream:
                os.fsync(stream.fileno())
            digest = _seal(stage, kind='restore', artifact_id=identity,
                source_identity=manifest['source_identity'], timestamp=request['timestamp'],
                policy=manifest['policy'], extra=receipt)
            _journal_event(journal, request, 'SEALED', dict(manifest_sha256=digest))
            _publish(stage, target)
            verify_bundle(target, expected_manifest_sha256=digest)
        _journal_event(journal, request, 'PUBLISHED', dict(target=str(target), manifest_sha256=digest))
        return dict(path=str(target), manifest_sha256=digest, quarantined=True)
    except BaseException as exc:
        try:
            _journal_event(journal, request, 'FAILED', dict(error=type(exc).__name__, message=str(exc)))
        except BaseException as audit_error:
            exc.add_note('Restore failure audit also failed: ' + repr(audit_error))
        raise
