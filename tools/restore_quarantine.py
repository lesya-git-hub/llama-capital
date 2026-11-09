"""Persistent inspection-only restore fence. No release operation exists."""
import json
from hashlib import sha256


def validate_fence(rows):
    if len(rows) != 1:
        raise ValueError('Missing restore quarantine evidence')
    row = rows[0]
    if row['id'] != 1 or row['quarantined'] != 1:
        raise ValueError('Invalid restore quarantine')
    payload = row['receipt_json']
    if not isinstance(payload, str) or len(payload) > 16384:
        raise ValueError('Invalid restore receipt size')
    if sha256(payload.encode()).hexdigest() != row['receipt_sha256']:
        raise ValueError('Restore receipt hash mismatch')
    receipt = json.loads(payload)
    for key in ('restore_id', 'request_sha256', 'backup_manifest_sha256', 'operator_id',
                'authorization_id', 'reason', 'timestamp', 'target'):
        if not isinstance(receipt.get(key), str) or not receipt[key].strip():
            raise ValueError('Incomplete restore authorization evidence')
    if receipt.get('policy') != 'quarantined_no_release_v1':
        raise ValueError('Incompatible restore quarantine policy')
    request = {k: v for k, v in receipt.items() if k not in ('policy', 'request_sha256')}
    canonical = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if sha256(canonical.encode()).hexdigest() != receipt['request_sha256']:
        raise ValueError('Restore request identity mismatch')
    return dict(row)


def read_restore_fence(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='restore_fence'").fetchone()
    if version != 4:
        if exists:
            raise ValueError('Restore schema downgrade; execution refused')
        return None
    cursor = db.execute('SELECT * FROM restore_fence')
    names = [d[0] for d in cursor.description]
    return validate_fence([dict(zip(names, tuple(r))) for r in cursor])


def install_restore_fence(db, receipt_json):
    if not db.in_transaction or db.execute('PRAGMA user_version').fetchone()[0] != 3:
        raise ValueError('Restore migration requires a strict v3 write transaction')
    read_restore_fence(db)
    db.execute('CREATE TABLE restore_fence (id INTEGER PRIMARY KEY CHECK(id=1), quarantined INTEGER NOT NULL CHECK(quarantined=1), receipt_json TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)')
    db.execute('INSERT INTO restore_fence VALUES (1,1,?,?)',
               (receipt_json, sha256(receipt_json.encode()).hexdigest()))
    db.execute('PRAGMA user_version=4')
    read_restore_fence(db)
