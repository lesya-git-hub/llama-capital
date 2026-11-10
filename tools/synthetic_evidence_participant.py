"""Isolated mock participant. Never opens or modifies an existing 1M/1N store."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3

from tools.evidence_admission_coordinator import require
from tools.evidence_admission_store import digest, encode

APP_ID = 0x4C4C5350


class SyntheticEvidenceParticipant:
    def __init__(self, path, *, create_source=None):
        self.path = Path(path)
        with closing(self.connect(create=create_source is not None)) as db:
            db.execute('BEGIN IMMEDIATE')
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables and create_source is not None:
                require(db.execute('PRAGMA application_id').fetchone()[0] == 0
                    and db.execute('PRAGMA user_version').fetchone()[0] == 0, 'INCOMPATIBLE_SYNTHETIC_PARTICIPANT')
                require(create_source.scope == 'synthetic_test', 'SYNTHETIC_SOURCE_REQUIRED')
                db.execute('CREATE TABLE source (id INTEGER PRIMARY KEY CHECK(id=1), source_id TEXT, instance_id TEXT, generation TEXT)')
                db.execute('INSERT INTO source VALUES (1,?,?,?)', (create_source.source_id, create_source.instance_id, create_source.generation))
                db.execute('CREATE TABLE outbox (mutation_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
            require(db.execute('PRAGMA application_id').fetchone()[0] == APP_ID
                and db.execute('PRAGMA user_version').fetchone()[0] == 1, 'INCOMPATIBLE_SYNTHETIC_PARTICIPANT')
            db.execute('SELECT * FROM source').fetchone()
            db.execute('SELECT * FROM outbox LIMIT 0')
            db.execute('COMMIT')

    def connect(self, create=False):
        db = sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
            uri=True, isolation_level=None, timeout=2)
        try:
            if not create:
                require(db.execute('PRAGMA application_id').fetchone()[0] == APP_ID
                    and db.execute('PRAGMA user_version').fetchone()[0] == 1, 'INCOMPATIBLE_SYNTHETIC_PARTICIPANT')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    def _load(self, db, mutation_id):
        row = db.execute('SELECT content,sha256 FROM outbox WHERE mutation_id=?', (mutation_id,)).fetchone()
        if row is None:
            raise KeyError(mutation_id)
        value = json.loads(row[0])
        require(encode(value) == row[0] and digest(value) == row[1]
            and value['mutation_id'] == mutation_id, 'CORRUPT_PARTICIPANT_RECEIPT')
        return value

    def load_receipt(self, mutation_id):
        with closing(self.connect()) as db:
            return self._load(db, mutation_id)

    def _before_commit(self, receipt):
        pass

    def _after_commit(self, receipt):
        pass

    def _decide(self, coordinator, fence, *, status, new_generation=None, token=None):
        if status == 'ABORTED':
            coordinator._principal('ABORT_PARTICIPANT', token, 'recovery')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            # The participant lock serializes apply against durable abort. The
            # coordinator cannot close an unresolved fence without this outbox.
            pending = coordinator.pending_fence(fence, recovery=status == 'ABORTED')
            source = db.execute('SELECT source_id,instance_id,generation FROM source WHERE id=1').fetchone()
            require(source is not None and source[:2] == (pending['source_id'], pending['instance_id']), 'SOURCE_INSTANCE_CONFLICT')
            try:
                old = self._load(db, fence.operation_id)
            except KeyError:
                old = None
            if old is not None:
                require(old['status'] == status and (status == 'ABORTED' or old['new_generation'] == new_generation), 'PARTICIPANT_DECISION_CONFLICT')
                return old
            require(source[2] == pending['expected_generation'], 'SOURCE_GENERATION_CONFLICT')
            if status == 'APPLIED':
                require(isinstance(new_generation, str) and new_generation.strip()
                    and new_generation != source[2], 'NEW_GENERATION_REQUIRED')
            receipt = dict(status=status, mutation_id=fence.operation_id, authority_id=fence.authority_id,
                fence_sha256=fence.sha256, source_id=source[0], instance_id=source[1], old_generation=source[2],
                new_generation=new_generation if status == 'APPLIED' else source[2])
            if status == 'APPLIED':
                db.execute('UPDATE source SET generation=? WHERE id=1', (new_generation,))
            db.execute('INSERT INTO outbox VALUES (?,?,?)', (fence.operation_id, encode(receipt), digest(receipt)))
            self._before_commit(receipt)
            db.execute('COMMIT')
        self._after_commit(receipt)
        return receipt

    def apply(self, coordinator, fence, *, new_generation):
        return self._decide(coordinator, fence, status='APPLIED', new_generation=new_generation)

    def abort(self, coordinator, fence, *, token):
        return self._decide(coordinator, fence, status='ABORTED', token=token)
