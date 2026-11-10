"""New synthetic FX SQLite journal. No migrations, repairs or trust promotion."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from models.fx_evidence import FXRecord, FXSnapshot, FXEvaluation
from tools.historical_snapshot import canonical_json, input_hash

APP_ID = 0x4C4C4658
MAX_EVENTS = 4096
MAX_JOURNAL_BYTES = 64 * 1024 * 1024


def journal_hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def generation(records):
    return journal_hash([r.model_dump(mode='json') for r in records])


class FXEvidenceArchive:
    def __init__(self, path, *, create=False):
        self.path = Path(path)
        with closing(self.connect(create=create)) as db:
            db.execute('BEGIN IMMEDIATE')
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            app, version = db.execute('PRAGMA application_id').fetchone()[0], db.execute('PRAGMA user_version').fetchone()[0]
            if create and not tables and app == version == 0:
                db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, previous_sha TEXT NOT NULL, sha TEXT NOT NULL)')
                db.execute('CREATE TABLE tail (id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL, sha TEXT NOT NULL)')
                db.execute('INSERT INTO tail VALUES (1,0,?)', ('0' * 64,))
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
            elif app != APP_ID or version != 1:
                raise ValueError('INCOMPATIBLE_FX_ARCHIVE')
            self._events(db)
            db.execute('COMMIT')

    def connect(self, *, create=False):
        db = sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
            uri=True, isolation_level=None, timeout=3)
        try:
            if not create and (db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('INCOMPATIBLE_FX_ARCHIVE')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    def _events(self, db):
        count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(content AS BLOB))),0) FROM events').fetchone()
        if count > MAX_EVENTS or size > MAX_JOURNAL_BYTES:
            raise ValueError('FX_JOURNAL_BUDGET')
        rows = db.execute('SELECT seq,identity,kind,content,previous_sha,sha FROM events ORDER BY seq').fetchall()
        if len(rows) > MAX_EVENTS:
            raise ValueError('FX_EVENT_BUDGET')
        previous = '0' * 64
        records, evaluations = [], []
        for expected, (seq, identity, kind, content, prior, digest) in enumerate(rows, 1):
            calculated = journal_hash([seq, identity, kind, content, prior])
            if seq != expected or previous != prior or calculated != digest:
                raise ValueError('FX_AUDIT_INTEGRITY')
            if kind == 'record':
                value = FXRecord.model_validate_json(content)
                if identity != 'record:' + value.receipt.observation_id or sha256(value.body()).hexdigest() != value.receipt.raw_sha256:
                    raise ValueError('FX_RECORD_INTEGRITY')
                records.append(value)
            elif kind == 'evaluation':
                value = FXEvaluation.model_validate_json(content)
                if identity != 'evaluation:' + value.request.evaluation_id:
                    raise ValueError('FX_EVALUATION_IDENTITY')
                evaluations.append(value)
            else:
                raise ValueError('UNKNOWN_FX_EVENT')
            if canonical_json(value) != content:
                raise ValueError('NONCANONICAL_FX_EVENT')
            previous = digest
        if db.execute('SELECT sequence,sha FROM tail WHERE id=1').fetchone() != (len(rows), previous) or db.execute('SELECT COUNT(*) FROM tail').fetchone()[0] != 1:
            raise ValueError('FX_AUDIT_TRUNCATED')
        return rows, records, evaluations

    def _snapshot(self, db):
        _, records, _ = self._events(db)
        return FXSnapshot(generation=generation(records), records=tuple(records))

    def snapshot(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            return self._snapshot(db)

    def _before_commit(self, kind):
        pass  # Deterministic failure injection; no background tasks.

    def _after_commit(self, kind):
        pass

    def _append(self, identity, kind, value, *, expected_generation=None):
        content = canonical_json(value)
        if len(content.encode()) > 32 * 1024 * 1024:
            raise ValueError('FX_EVENT_BYTE_BUDGET')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            rows, _, _ = self._events(db)
            old = next((row for row in rows if row[1] == identity), None)
            if old:
                if old[2:4] != (kind, content):
                    raise ValueError('IMMUTABLE_FX_IDENTITY_CONFLICT')
                return input_hash(value)
            if len(rows) >= MAX_EVENTS:
                raise ValueError('FX_EVENT_BUDGET')
            if sum(len(row[3].encode()) for row in rows) + len(content.encode()) > MAX_JOURNAL_BYTES:
                raise ValueError('FX_JOURNAL_BUDGET')
            if expected_generation is not None and self._snapshot(db).generation != expected_generation:
                raise ValueError('FX_SOURCE_CHANGED_BEFORE_RESULT_COMMIT')
            seq, previous = len(rows) + 1, rows[-1][5] if rows else '0' * 64
            digest = journal_hash([seq, identity, kind, content, previous])
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)', (seq, identity, kind, content, previous, digest))
            db.execute('UPDATE tail SET sequence=?,sha=? WHERE id=1', (seq, digest))
            self._before_commit(kind)
            db.execute('COMMIT')
        self._after_commit(kind)
        return input_hash(value)

    def record(self, record):
        record = FXRecord.model_validate(record.model_dump(mode='json'))
        if sha256(record.body()).hexdigest() != record.receipt.raw_sha256:
            raise ValueError('RAW_HASH_MISMATCH')
        return self._append('record:' + record.receipt.observation_id, 'record', record)

    def save_evaluation(self, evaluation):
        from tools.fx_evidence_evaluator import replay_fx
        evaluation = FXEvaluation.model_validate(evaluation.model_dump(mode='json'))
        replay_fx(evaluation, expected_hash=input_hash(evaluation))
        return self._append('evaluation:' + evaluation.request.evaluation_id, 'evaluation', evaluation,
            expected_generation=evaluation.snapshot.generation)

    def load_evaluation(self, identity, *, expected_hash):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            _, _, values = self._events(db)
            value = next((v for v in values if v.request.evaluation_id == identity), None)
            if value is None or input_hash(value) != expected_hash:
                raise ValueError('MISSING_OR_CORRUPT_FX_EVALUATION')
            return value
