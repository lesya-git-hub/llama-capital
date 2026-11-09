"""Synthetic candidate evaluation, no publication or production trust interface."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from models.calendar_finality_evidence import EligibilityRequest, EvidenceManifest, EligibilityResult
from providers.provisional_market_data import ProvisionalBatch
from tools.calendar_finality_compiler import compile_calendar, compile_provider_evidence
from tools.historical_snapshot import canonical_json, input_hash
from tools.market_verification import TrustRegistry, TrustPin, VerificationPolicy
from tools.verified_daily_pipeline import freeze_verified_daily_inputs


def engine_hash():
    root = Path(__file__).resolve().parents[1]
    digest = sha256()
    for name in ('models/calendar_finality_evidence.py', 'tools/calendar_finality_store.py',
                 'tools/calendar_finality_compiler.py', 'tools/calendar_finality_review.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    return digest.hexdigest()


def _archive_snapshot(archive, batch):
    """Read the entire relevant 1M history in one read snapshot, including reverse conflicts.

    Its schema is inspected read-only; 1M itself is never migrated or changed.
    Any changed overlapping normalized candle is held; no resolution override.
    """
    with closing(sqlite3.connect(archive.path.resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        from providers.provisional_market_data import APP_ID, NormalizedObservation
        if db.execute('PRAGMA application_id').fetchone()[0] != APP_ID or db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Incompatible provisional archive')
        rows = {}
        for table, ordering in (('observations', 'sequence'), ('normalization', 'observation_id,context_sha256'),
                                ('conflicts', 'observation_id,previous_id,sha256'), ('batches', 'batch_id')):
            rows[table] = db.execute(f'SELECT * FROM {table} ORDER BY {ordering}').fetchall()
        generation = sha256(repr(rows).encode()).hexdigest()
        target = {o.metadata.ticker: o for o in batch.observations}
        changed = False
        for identity, context, content, digest in rows['normalization']:
            if sha256(content.encode()).hexdigest() != digest:
                raise ValueError('Normalization history integrity mismatch')
            data = json.loads(content)
            if data['status'] != 'PROVISIONAL':
                continue
            prior = NormalizedObservation.model_validate(data)
            current = target.get(prior.metadata.ticker)
            if current is None:
                continue
            archive._load(db, identity)
            keys = ('fixture_kind', 'provider_id', 'dataset_id', 'feed', 'ticker')
            if any(getattr(prior.metadata, k) != getattr(current.metadata, k) for k in keys):
                continue
            expected = {b.date: input_hash(b) for b in current.snapshot.bars}
            if any(b.date in expected and expected[b.date] != input_hash(b) for b in prior.snapshot.bars):
                changed = True
        for identity, previous, content, digest in rows['conflicts']:
            if sha256(content.encode()).hexdigest() != digest:
                raise ValueError('Conflict history integrity mismatch')
            if identity in {o.metadata.observation_id for o in batch.observations} or previous in {o.metadata.observation_id for o in batch.observations}:
                changed = True
        return generation, changed


def evaluate_candidate(archive, store, request, manifest, *, review_id=None, review_sha256=None):
    request = EligibilityRequest.model_validate(request.model_dump(mode='json'))
    manifest = EvidenceManifest.model_validate(manifest.model_dump(mode='json'))
    records, corpus = store.snapshot()
    batch = archive.load_batch(request.batch_id, expected_sha256=request.batch_sha256)
    archive_corpus, conflicts = _archive_snapshot(archive, batch)
    reasons, calendar_valid, finality_valid, projection = [], False, False, None
    result_scope = request.scope
    if (request.scope != 'synthetic_test' or batch.calendar.scope != 'synthetic_test'
            or any(o.metadata.fixture_kind != 'synthetic_test' for o in batch.observations)):
        reasons.append('REAL_OBSERVATIONS_REMAIN_PROVISIONAL')
        result_scope = 'real'
        status = 'PROVISIONAL'
    else:
        if input_hash(manifest) != request.manifest_sha256:
            reasons.append('MANIFEST_HASH_MISMATCH')
        if conflicts:
            reasons.append('UNRESOLVED_ARCHIVE_REVISION_CONFLICT')
        try:
            calendar = compile_calendar(records, manifest, at=request.verified_at)
            if calendar != batch.calendar:
                raise ValueError('Reviewed calendar differs from archived calendar')
            calendar_valid = True
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            reasons.append('CALENDAR_REJECTED:' + str(exc))
        try:
            evidence = compile_provider_evidence(records, manifest, batch, at=request.verified_at)
            finality_valid = True
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            reasons.append('FINALITY_REJECTED:' + str(exc))
        try:
            review = store.load_review(review_id, review_sha256)
            if (review.scope != 'synthetic_test' or not review.approved or review.request_sha256 != input_hash(request)
                    or review.corpus_sha256 != corpus or review.reviewed_at > request.verified_at
                    or any(r.receipt.acquired_end > review.reviewed_at for r in records.values())):
                raise ValueError('Stale, denied or inconsistent synthetic review')
        except (ValueError, TypeError) as exc:
            reasons.append('REVIEW_REJECTED:' + str(exc))
        if not reasons:
            # Hard-coded synthetic root is local to a dry evaluation. Never a
            # production registry or a publication action.
            trust = TrustRegistry(mode='synthetic_test', pins=tuple(TrustPin(kind=kind,
                scope='synthetic_test', source=obj.source, version=obj.version, sha256=input_hash(obj),
                review_reference=review.review_id) for kind, obj in (('calendar', calendar), ('provider_evidence', evidence))))
            observed = []
            from models.daily_signals import ObservedTicker, BarAvailability
            for observation in batch.observations:
                observed.append(ObservedTicker(snapshot=observation.snapshot, fetched_at=observation.metadata.acquired_end,
                    finality_source='SYNTHETIC REVIEW ONLY:' + review.review_id,
                    availability=tuple(BarAvailability(date=b.date, available_at=observation.metadata.acquired_end, final=True)
                                       for b in observation.snapshot.bars)))
            try:
                projected = freeze_verified_daily_inputs(calendar, tuple(observed), evidence,
                    policy=VerificationPolicy(publication_delay_seconds=request.publication_delay_seconds),
                    verified_at=request.verified_at, decision_at=request.decision_at, trust=trust)
                projection = canonical_json(projected)
            except (ValueError, TypeError) as exc:
                finality_valid = False
                reasons.append('EXISTING_1C_REJECTED:' + str(exc))
        status = 'HELD_FOR_REVIEW' if reasons else 'ELIGIBLE_FOR_1C_PROJECTION'
    result = EligibilityResult(scope=result_scope, status=status, request=request, manifest=manifest,
        review_id=review_id, review_sha256=review_sha256, corpus_sha256=corpus, archive_corpus_sha256=archive_corpus,
        calendar_valid=calendar_valid, finality_valid=finality_valid, reasons=tuple(reasons),
        synthetic_projection_json=projection, engine_sha256=engine_hash())
    if _archive_snapshot(archive, batch)[0] != archive_corpus:
        raise ValueError('Provisional archive changed during evaluation')
    store.save_evaluation(result)  # Corpus CAS + audit commit before returned success.
    return result


def replay_candidate(archive, store, *, request_id, expected_sha256, review_id=None):
    old = store.load_evaluation(request_id, expected_sha256)
    if old.engine_sha256 != engine_hash():
        raise ValueError('Evidence evaluation implementation changed')
    if review_id is not None and review_id != old.review_id:
        raise ValueError('Replay review identity differs')
    # Re-evaluation uses current corpora. Changed history is a refusal, never a
    # silent rewrite of an old result or fresh authorization from historical pins.
    _, corpus = store.snapshot()
    batch = archive.load_batch(old.request.batch_id, expected_sha256=old.request.batch_sha256)
    archive_corpus, _ = _archive_snapshot(archive, batch)
    if corpus != old.corpus_sha256 or archive_corpus != old.archive_corpus_sha256:
        raise ValueError('Evidence/archive history changed; retain old result and request new review')
    value = evaluate_candidate(archive, store, old.request, old.manifest,
        review_id=old.review_id, review_sha256=old.review_sha256)
    if value != old:
        raise ValueError('Offline evidence replay differs')
    return value
