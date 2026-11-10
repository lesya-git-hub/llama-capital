"""Single SQLite authority journal for synthetic admission; no distributed commit."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from models.evidence_admission import Checkpoint, CommitReceipt

APP_ID = 0x4C4C4143
MAX_EVENTS = 10000
MAX_BUNDLES = 64


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(encode(value).encode()).hexdigest()


class AdmissionStore:
    def __init__(self, path, *, create_authority_id=None):
        self.path = Path(path)
        with closing(self.connect(create=create_authority_id is not None)) as db:
            db.execute('BEGIN IMMEDIATE')
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables and app == 0 and version == 0 and create_authority_id:
                db.execute('CREATE TABLE authority (id INTEGER PRIMARY KEY CHECK(id=1), authority_id TEXT NOT NULL, sequence INTEGER NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('INSERT INTO authority VALUES (1,?,0,?)', (create_authority_id, '0' * 64))
                db.execute('CREATE TABLE events (sequence INTEGER PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL, request_sha256 TEXT NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundles (bundle_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE objects (object_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
            elif app != APP_ID or version != 1:
                raise ValueError('Incompatible admission store; no automatic migration/repair')
            for table in ('authority', 'events', 'bundles', 'objects'):
                db.execute(f'SELECT * FROM {table} LIMIT 0')
            self.events(db)
            db.execute('COMMIT')

    def connect(self, create=False):
        db = sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
            uri=True, isolation_level=None, timeout=2)
        try:
            if not create and (db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('Admission store identity mismatch')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    def events(self, db):
        meta = db.execute('SELECT authority_id,sequence,sha256 FROM authority WHERE id=1').fetchone()
        if meta is None or db.execute('SELECT COUNT(*) FROM authority').fetchone()[0] != 1:
            raise ValueError('Missing authority identity')
        rows = db.execute('SELECT sequence,operation_id,request_sha256,content,sha256 FROM events ORDER BY sequence').fetchall()
        if len(rows) > MAX_EVENTS:
            raise ValueError('Admission event budget exceeded')
        previous, events, prior_time = '0' * 64, [], None
        for index, (seq, op, request_hash, content, event_hash) in enumerate(rows, 1):
            event = json.loads(content)
            stamp = datetime.fromisoformat(event['timestamp'])
            if (seq != index or event['sequence'] != seq or event['operation_id'] != op
                    or event['request_sha256'] != request_hash or event['previous_sha256'] != previous
                    or event['authority_id'] != meta[0] or encode(event) != content or digest(event) != event_hash
                    or stamp.tzinfo is None or prior_time is not None and stamp < prior_time):
                raise ValueError('Admission audit chain integrity mismatch')
            events.append(event | {'event_sha256': event_hash})
            previous, prior_time = event_hash, stamp
        if meta[1:] != (len(rows), previous):
            raise ValueError('Missing/truncated admission audit history')
        return meta[0], events

    def append(self, db, *, operation_id, request_sha256, action, actor, timestamp, payload):
        authority, events = self.events(db)
        if len(events) >= MAX_EVENTS:
            raise ValueError('Admission event budget exceeded')
        if events and timestamp < datetime.fromisoformat(events[-1]['timestamp']):
            raise ValueError('Clock moved backwards; serving must remain held')
        event = dict(sequence=len(events) + 1, operation_id=operation_id, request_sha256=request_sha256,
            previous_sha256=events[-1]['event_sha256'] if events else '0' * 64,
            authority_id=authority, action=action, actor=actor, timestamp=timestamp.isoformat(), payload=payload)
        event_hash = digest(event)
        db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (event['sequence'], operation_id, request_sha256, encode(event), event_hash))
        db.execute('UPDATE authority SET sequence=?,sha256=? WHERE id=1', (event['sequence'], event_hash))
        return CommitReceipt(authority_id=authority, operation_id=operation_id, event_action=action,
            sequence=event['sequence'], sha256=event_hash)

    def checkpoint(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            authority, events = self.events(db)
            if not events:
                raise ValueError('Authority has not booted')
            return Checkpoint(authority_id=authority, sequence=len(events), sha256=events[-1]['event_sha256'],
                epoch=sum(e['action'] == 'BOOT' for e in events))
