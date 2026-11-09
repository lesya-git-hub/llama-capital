"""Separate immutable offline evidence corpus. No trust registry management."""
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sqlite3

from models.calendar_finality_evidence import SourceReceipt, ReviewDisposition
from tools.historical_snapshot import canonical_json, input_hash

APP_ID = 0x4C4C4546
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 4096


@dataclass(frozen=True)
class SourceRecord:
    receipt: SourceReceipt
    body: bytes


def record_hash(record):
    return sha256(canonical_json(record.receipt).encode() + b'\0' + record.body).hexdigest()


class EvidenceStore:
    def __init__(self, path):
        self.path = Path(path)
        with closing(self._connect(create=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables and app == 0 and version == 0:
                db.execute('CREATE TABLE sources (sequence INTEGER PRIMARY KEY, receipt_id TEXT UNIQUE NOT NULL, content TEXT NOT NULL, body BLOB NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE reviews (review_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE evaluations (request_id TEXT PRIMARY KEY, content TEXT NOT NULL, sha256 TEXT NOT NULL)')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
            elif app != APP_ID or version != 1:
                raise ValueError('Incompatible evidence store; no repair/migration')
            for table in ('sources', 'reviews', 'evaluations'):
                db.execute(f'SELECT * FROM {table} LIMIT 0')
            db.execute('COMMIT')

    def _connect(self, create=False):
        db = sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
            uri=True, isolation_level=None, timeout=2)
        try:
            if not create and (db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('Incompatible evidence store')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    def _corpus(self, db):
        records, hashes, heads = {}, [], {}
        rows = db.execute('SELECT receipt_id,content,body,sha256 FROM sources ORDER BY sequence').fetchall()
        if len(rows) > MAX_RECORDS:
            raise ValueError('Evidence corpus budget exceeded')
        for identity, content, body, digest in rows:
            receipt = SourceReceipt.model_validate_json(content)
            record = SourceRecord(receipt, body)
            if (type(body) is not bytes or len(body) > MAX_BYTES or receipt.receipt_id != identity
                    or canonical_json(receipt) != content or sha256(body).hexdigest() != receipt.body_sha256
                    or record_hash(record) != digest):
                raise ValueError('Source evidence integrity mismatch')
            key = (receipt.scope, receipt.kind, receipt.source, receipt.logical_key)
            prior = heads.get(key)
            if receipt.previous_id != prior:
                raise ValueError('Missing/forked revision history')
            if prior and receipt.acquired_end < records[prior].receipt.acquired_end:
                raise ValueError('Backwards revision chronology')
            heads[key] = identity
            records[identity] = record
            hashes.append((identity, digest))
        generation = sha256(repr(hashes).encode()).hexdigest()
        return records, generation

    def snapshot(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            return self._corpus(db)

    def record_source(self, record):
        receipt = SourceReceipt.model_validate(record.receipt.model_dump(mode='json'))
        record = SourceRecord(receipt, record.body)
        if type(record.body) is not bytes or len(record.body) > MAX_BYTES or sha256(record.body).hexdigest() != receipt.body_sha256:
            raise ValueError('Raw evidence hash/size mismatch')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            records, _ = self._corpus(db)
            old = records.get(receipt.receipt_id)
            if old and old != record:
                raise ValueError('Immutable evidence ID conflict')
            if not old:
                if len(records) >= MAX_RECORDS:
                    raise ValueError('Evidence corpus budget exceeded')
                key = (receipt.scope, receipt.kind, receipt.source, receipt.logical_key)
                prior = next((r.receipt for r in reversed(tuple(records.values()))
                    if (r.receipt.scope, r.receipt.kind, r.receipt.source, r.receipt.logical_key) == key), None)
                if receipt.previous_id != (prior.receipt_id if prior else None):
                    raise ValueError('Explicit current revision predecessor required')
                if prior and receipt.acquired_end < prior.acquired_end:
                    raise ValueError('Backwards revision chronology')
                db.execute('INSERT INTO sources (receipt_id,content,body,sha256) VALUES (?,?,?,?)',
                    (receipt.receipt_id, canonical_json(receipt), record.body, record_hash(record)))
            db.execute('COMMIT')
        return record_hash(record)

    def _immutable(self, table, identity, content, *, expected_corpus=None, eligible_result=None):
        digest = sha256(content.encode()).hexdigest()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if expected_corpus is not None and self._corpus(db)[1] != expected_corpus:
                raise ValueError('Evidence changed before durable review/evaluation commit')
            if eligible_result is not None:
                review = self._review(db, eligible_result.review_id, eligible_result.review_sha256)
                if (not review.approved or review.scope != 'synthetic_test'
                        or review.request_sha256 != input_hash(eligible_result.request)
                        or review.corpus_sha256 != expected_corpus):
                    raise ValueError('Eligible result lacks current authorized review evidence')
            old = db.execute(f'SELECT content,sha256 FROM {table} WHERE {"review_id" if table == "reviews" else "request_id"}=?', (identity,)).fetchone()
            if old and old != (content, digest):
                raise ValueError('Immutable review/evaluation conflict')
            if not old:
                db.execute(f'INSERT INTO {table} VALUES (?,?,?)', (identity, content, digest))
            db.execute('COMMIT')
        return digest

    def record_review(self, review, *, authorize=None):
        review = ReviewDisposition.model_validate(review.model_dump(mode='json'))
        if review.scope != 'synthetic_test' or not callable(authorize) or authorize(review) is not True:
            raise PermissionError('Stage A requires independently authorized synthetic review')
        _, corpus = self.snapshot()
        if review.corpus_sha256 != corpus:
            raise ValueError('Review names stale evidence corpus')
        return self._immutable('reviews', review.review_id, canonical_json(review), expected_corpus=review.corpus_sha256)

    def load_review(self, identity, expected_sha256):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            return self._review(db, identity, expected_sha256)

    def _review(self, db, identity, expected_sha256):
        reviews = {}
        for review_id, content, digest in db.execute('SELECT review_id,content,sha256 FROM reviews'):
            review = ReviewDisposition.model_validate_json(content)
            if (sha256(content.encode()).hexdigest() != digest or review.review_id != review_id
                    or canonical_json(review) != content):
                raise ValueError('Review history integrity mismatch')
            reviews[review_id] = (review, digest)
        if identity not in reviews or reviews[identity][1] != expected_sha256:
            raise ValueError('Missing/inconsistent review evidence')
        review = reviews[identity][0]
        if any(other.review_id != identity and other.request_sha256 == review.request_sha256
               for other, _ in reviews.values()):
            raise ValueError('Conflicting review decisions for the same request; new request required')
        return review

    def save_evaluation(self, result):
        from models.calendar_finality_evidence import EligibilityResult
        result = EligibilityResult.model_validate(result.model_dump(mode='json'))
        return self._immutable('evaluations', result.request.request_id, canonical_json(result),
            expected_corpus=result.corpus_sha256,
            eligible_result=result if result.status == 'ELIGIBLE_FOR_1C_PROJECTION' else None)

    def load_evaluation(self, identity, expected_sha256):
        from models.calendar_finality_evidence import EligibilityResult
        with closing(self._connect()) as db:
            row = db.execute('SELECT content,sha256 FROM evaluations WHERE request_id=?', (identity,)).fetchone()
        if not row or row[1] != expected_sha256 or sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError('Missing/inconsistent evaluation evidence')
        value = EligibilityResult.model_validate_json(row[0])
        if value.request.request_id != identity:
            raise ValueError('Evaluation identity mismatch')
        return value
