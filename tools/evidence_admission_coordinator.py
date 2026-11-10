"""Synthetic coordinator. No production writer, registry, publication or financial API."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import base64

from models.evidence_admission import (AdmissionBundle, Checkpoint, CommitReceipt,
    EvidenceObject, ObservationBinding, Principal, ReviewRequest, SourceVersion)
from tools.evidence_admission_store import AdmissionStore, MAX_BUNDLES, digest, encode
from tools.historical_snapshot import canonical_json, input_hash
from models.daily_signals import DAILY_UNIVERSE


class AdmissionRejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AdmissionRejected(message)


def validate_bundle(bundle):
    """Recompute synthetic 1M/1N/1C evidence; evaluation is never authorization."""
    from tools.calendar_finality_store import SourceRecord, record_hash
    from tools.calendar_finality_compiler import compile_calendar, compile_provider_evidence
    from tools.market_verification import TrustRegistry, TrustPin, verify_candle_finality
    from tools.verified_daily_pipeline import VerifiedDailyInputs, verification_source_sha256
    from providers.provisional_market_data import normalize_recorded, RecordedResponse
    from tools.calendar_finality_review import engine_hash
    from models.calendar_finality_evidence import ReviewDisposition

    bundle = AdmissionBundle.model_validate(bundle.model_dump(mode='json'))
    require(bundle.scope == 'synthetic_test' and bundle.batch.calendar.scope == 'synthetic_test', 'REAL_EVIDENCE_PROVISIONAL')
    require(bundle.evaluation.scope == 'synthetic_test' and bundle.evaluation.status == 'ELIGIBLE_FOR_1C_PROJECTION', 'EVALUATION_NOT_ELIGIBLE')
    require(bundle.evaluation.engine_sha256 == engine_hash(), 'STAGE_A_ENGINE_CHANGED')
    require(input_hash(bundle.batch) == bundle.evaluation.request.batch_sha256, 'BATCH_EVALUATION_CONFLICT')
    require(len(bundle.objects) <= 256, 'OBJECT_BUDGET')
    objects = {o.object_id: o for o in bundle.objects}
    require(len(objects) == len(bundle.objects) and all(o.scope == 'synthetic_test' for o in bundle.objects), 'OBJECT_SCOPE_OR_ID_CONFLICT')
    visited, visiting = set(), set()
    def visit(identity):
        require(identity in objects and identity not in visiting, 'MISSING_OR_CYCLIC_DEPENDENCY')
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in objects[identity].dependencies:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)
    for identity in objects:
        visit(identity)
    require(len(bundle.sources) == 2 and len({s.source_id for s in bundle.sources}) == 2, 'TWO_SYNTHETIC_SOURCE_VERSIONS_REQUIRED')
    require(tuple(b.ticker for b in bundle.observations) == DAILY_UNIVERSE, 'INCOMPLETE_SIX_STOCK_BINDINGS')
    require(len({b.object_id for b in bundle.observations}) == 6, 'DUPLICATE_RAW_BINDING')
    for observation, binding in zip(bundle.batch.observations, bundle.observations):
        require(observation.metadata.fixture_kind == 'synthetic_test' and binding.observation_id == observation.metadata.observation_id, 'REAL_OR_WRONG_OBSERVATION')
        raw = objects.get(binding.object_id)
        require(raw is not None and raw.kind == 'raw_observation', 'MISSING_RAW_OBSERVATION')
        require(sha256(raw.body()).hexdigest() == observation.metadata.raw_sha256, 'RAW_HASH_CONFLICT')
        replay = normalize_recorded(RecordedResponse(observation.metadata, raw.body()), bundle.batch.calendar, as_of=bundle.batch.as_of)
        require(replay == observation, 'NORMALIZATION_REPLAY_CONFLICT')
    records = {}
    for obj in bundle.objects:
        if obj.kind == 'source_receipt':
            require(obj.source_receipt is not None and obj.source_receipt.scope == 'synthetic_test', 'MISSING_SYNTHETIC_SOURCE_RECEIPT')
            require(sha256(obj.body()).hexdigest() == obj.source_receipt.body_sha256, 'SOURCE_BODY_HASH_CONFLICT')
            require(obj.source_receipt.receipt_id not in records, 'DUPLICATE_SOURCE_RECEIPT')
            records[obj.source_receipt.receipt_id] = SourceRecord(obj.source_receipt, obj.body())
        require(obj.kind != 'fx_placeholder', 'FX_NOT_INCLUDED_IN_THIS_PURPOSE')
    # Preserve original corpus order in the object tuple, matching 1N lineage.
    heads = {}
    hashes = []
    for identity, record in records.items():
        r = record.receipt
        key = (r.scope, r.kind, r.source, r.logical_key)
        require(r.previous_id == heads.get(key), 'SOURCE_REVISION_HISTORY_CONFLICT')
        heads[key] = identity
        hashes.append((identity, record_hash(record)))
    require(sha256(repr(hashes).encode()).hexdigest() == bundle.evaluation.corpus_sha256, 'SOURCE_CORPUS_CONFLICT')
    upstream = objects.get('upstream-review:' + bundle.evaluation.review_id)
    require(upstream is not None and upstream.kind == 'policy', 'UPSTREAM_REVIEW_REQUIRED')
    upstream_review = ReviewDisposition.model_validate_json(upstream.body())
    require(input_hash(upstream_review) == bundle.evaluation.review_sha256
        and upstream_review.review_id == bundle.evaluation.review_id
        and upstream_review.scope == 'synthetic_test' and upstream_review.approved
        and upstream_review.request_sha256 == input_hash(bundle.evaluation.request)
        and upstream_review.corpus_sha256 == bundle.evaluation.corpus_sha256
        and upstream_review.reviewed_at <= bundle.evaluation.request.verified_at
        and all(r.receipt.acquired_end <= upstream_review.reviewed_at for r in records.values()),
        'UPSTREAM_REVIEW_CONFLICT')
    manifest = bundle.evaluation.manifest
    require(input_hash(manifest) == bundle.evaluation.request.manifest_sha256, 'MANIFEST_CONFLICT')
    cal = compile_calendar(records, manifest, at=bundle.evaluation.request.verified_at)
    evidence = compile_provider_evidence(records, manifest, bundle.batch, at=bundle.evaluation.request.verified_at)
    projected = VerifiedDailyInputs.model_validate_json(bundle.evaluation.synthetic_projection_json)
    require(projected.scope == 'synthetic_test' and cal == bundle.batch.calendar == projected.calendar
            and evidence == projected.evidence, 'SYNTHETIC_PROJECTION_CONFLICT')
    require(projected.verification_source_sha256 == verification_source_sha256(), 'VERIFIER_ENVIRONMENT_CONFLICT')
    require(tuple(o.snapshot for o in bundle.batch.observations) == projected.daily_inputs.snapshot.tickers, 'PROJECTION_SNAPSHOT_CONFLICT')
    require(projected.verified_at == bundle.evaluation.request.verified_at
        and projected.daily_inputs.decision_at == bundle.evaluation.request.decision_at
        and projected.policy.publication_delay_seconds == bundle.evaluation.request.publication_delay_seconds,
        'PROJECTION_POLICY_OR_TIME_CONFLICT')
    for original, observed in zip(bundle.batch.observations, projected.daily_inputs.observed):
        require(observed.fetched_at == original.metadata.acquired_end
            and observed.finality_source == 'SYNTHETIC REVIEW ONLY:' + bundle.evaluation.review_id
            and all(a.final and a.available_at == original.metadata.acquired_end for a in observed.availability),
            'PROJECTION_ACQUISITION_CONFLICT')
    trust = TrustRegistry(mode='synthetic_test', pins=tuple(TrustPin(kind=kind, scope='synthetic_test',
        source=value.source, version=value.version, sha256=input_hash(value), review_reference=bundle.evaluation.review_id)
        for kind, value in (('calendar', cal), ('provider_evidence', evidence))))
    require(input_hash(trust) == projected.trust_registry_sha256, 'SYNTHETIC_REGISTRY_BINDING_CONFLICT')
    require(verify_candle_finality(projected.daily_inputs, cal, evidence, policy=projected.policy,
        verified_at=projected.verified_at, trust=trust) == projected.records, 'FINALITY_REPLAY_CONFLICT')
    return bundle


def prepare_from_stage_a(archive, evidence_store, *, batch_id, batch_sha256, evaluation_id,
                       evaluation_sha256, bundle_id, prepared_by, sources):
    """Logical read-only imports. No existing writer is fenced or integrated."""
    from tools.calendar_finality_review import _archive_snapshot, engine_hash
    batch = archive.load_batch(batch_id, expected_sha256=batch_sha256)
    evaluation = evidence_store.load_evaluation(evaluation_id, evaluation_sha256)
    require(evaluation.scope == 'synthetic_test', 'REAL_EVIDENCE_PROVISIONAL')
    require(evaluation.engine_sha256 == engine_hash(), 'STAGE_A_ENGINE_CHANGED')
    records, corpus = evidence_store.snapshot()
    archive_generation, conflicts = _archive_snapshot(archive, batch)
    require(not conflicts and corpus == evaluation.corpus_sha256 and archive_generation == evaluation.archive_corpus_sha256, 'STALE_OR_CONFLICTING_SOURCE_IMPORT')
    review = evidence_store.load_review(evaluation.review_id, evaluation.review_sha256)
    require(review.approved and review.request_sha256 == input_hash(evaluation.request), 'SOURCE_REVIEW_CONFLICT')
    require(tuple(s.generation for s in sources) == (archive_generation, corpus), 'SOURCE_VECTOR_IMPORT_CONFLICT')
    objects, bindings = [], []
    for observation in batch.observations:
        record = archive.load(observation.metadata.observation_id)
        identity = 'raw:' + observation.metadata.observation_id
        objects.append(EvidenceObject(object_id=identity, version='1', kind='raw_observation', body_b64=base64.b64encode(record.body).decode()))
        bindings.append(ObservationBinding(ticker=observation.metadata.ticker, observation_id=observation.metadata.observation_id, object_id=identity))
    for identity, record in records.items():
        objects.append(EvidenceObject(object_id='source:' + identity, version=record.receipt.version,
            kind='source_receipt', body_b64=base64.b64encode(record.body).decode(), source_receipt=record.receipt))
    # Review is retained as an immutable dependency, but does not grant coordinator authority.
    objects.append(EvidenceObject(object_id='upstream-review:' + review.review_id, version='1', kind='policy',
        body_b64=base64.b64encode(canonical_json(review).encode()).decode()))
    bundle = AdmissionBundle(bundle_id=bundle_id, version='1', prepared_by=prepared_by, sources=tuple(sources),
        batch=batch, evaluation=evaluation, objects=tuple(objects), observations=tuple(bindings))
    validate_bundle(bundle)
    require(evidence_store.snapshot()[1] == corpus and _archive_snapshot(archive, batch)[0] == archive_generation, 'SOURCE_CHANGED_DURING_IMPORT')
    return bundle


class EvidenceAdmissionCoordinator:
    def __init__(self, path, *, authenticate, clock, create_authority_id=None):
        self.store = AdmissionStore(path, create_authority_id=create_authority_id)
        self.authenticate, self.clock, self._fatal = authenticate, clock, False
        with closing(self.store.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            _, events = self.store.events(db)
            epoch = sum(e['action'] == 'BOOT' for e in events) + 1
            self.store.append(db, operation_id='system:boot:' + str(epoch), request_sha256=digest({'epoch': epoch}),
                action='BOOT', actor={'principal_id': 'system:startup', 'roles': []}, timestamp=self._now(), payload={'epoch': epoch})
            db.execute('COMMIT')
            self.epoch = epoch

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Trusted synthetic clock must return an aware datetime')
        return value.astimezone(timezone.utc)

    def _principal(self, action, token, role):
        value = self.authenticate(action, token)
        if not isinstance(value, Principal):
            raise PermissionError('Independent synthetic authentication required')
        value = Principal.model_validate(value.model_dump(mode='json'))
        if role not in value.roles:
            raise PermissionError('Unauthorized coordinator role')
        return value

    def _fold(self, events):
        state = dict(epoch=0, serving=False, sources={}, pending={}, bundles={}, evaluations={}, reviews={},
                     grants={}, revoked=set(), quarantined=set())
        for event in events:
            action, p = event['action'], event['payload']
            if action == 'BOOT':
                if p['epoch'] != state['epoch'] + 1:
                    raise ValueError('Invalid authority boot epoch')
                state['epoch'], state['serving'] = p['epoch'], False
                state['quarantined'].update(state['bundles'])
            elif action == 'RECOVER': state['serving'] = True
            elif action == 'REGISTER_SOURCE': state['sources'][p['source_id']] = p
            elif action == 'PREPARE': state['bundles'][p['bundle_id']] = p
            elif action == 'EVALUATE': state['evaluations'][p['bundle_id']] = p
            elif action == 'REVIEW': state['reviews'].setdefault(p['bundle_id'], []).append(p | {'actor': event['actor']['principal_id']})
            elif action == 'ADMIT': state['grants'][p['bundle_id']] = p
            elif action == 'REVOKE': state['revoked'].add((p['target_kind'], p['target_id']))
            elif action == 'QUARANTINE': state['quarantined'].add(p['bundle_id'])
            elif action == 'BEGIN_MUTATION':
                state['pending'][event['operation_id']] = p | {'receipt_sequence': event['sequence'], 'receipt_sha256': event['event_sha256']}
                state['quarantined'].update(b for b, summary in state['bundles'].items() if any(s['source_id'] == p['source_id'] for s in summary['sources']))
            elif action in ('FINISH_MUTATION', 'ABORT_MUTATION'):
                del state['pending'][p['mutation_id']]
                if action == 'FINISH_MUTATION': state['sources'][p['source']['source_id']] = p['source']
            elif action not in ('DENIED', 'QUALIFIED_READ'):
                raise ValueError('Unknown coordinator audit action')
        return state

    def _bundle(self, db, identity):
        row = db.execute('SELECT content,sha256 FROM bundles WHERE bundle_id=?', (identity,)).fetchone()
        if not row or sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError('Missing/corrupt sealed bundle')
        bundle = AdmissionBundle.model_validate_json(row[0])
        if bundle.bundle_id != identity or input_hash(bundle) != row[1]:
            raise ValueError('Sealed bundle identity mismatch')
        _, events = self.store.events(db)
        prepared = [e['payload'] for e in events if e['action'] == 'PREPARE' and e['payload']['bundle_id'] == identity]
        if len(prepared) != 1 or prepared[0]['bundle_sha256'] != row[1]:
            raise ValueError('Sealed bundle differs from authoritative preparation')
        for obj in bundle.objects:
            stored = db.execute('SELECT content,sha256 FROM objects WHERE object_id=?', (obj.object_id,)).fetchone()
            content = canonical_json(obj)
            if stored != (content, sha256(content.encode()).hexdigest()):
                raise ValueError('Missing/corrupt sealed dependency')
        return bundle

    def _state(self, state, identity, now):
        summary = state['bundles'].get(identity)
        require(summary is not None, 'UNKNOWN_BUNDLE')
        grant = state['grants'].get(identity)
        targets = [('bundle', identity), ('policy', 'synthetic-policy-v1')]
        targets += [('object', p) for p in summary['fingerprints']]
        targets += [('source', s['source_id']) for s in summary['sources']]
        targets += [('review', r['review_id']) for r in state['reviews'].get(identity, [])]
        if grant: targets.append(('grant', grant['grant_id']))
        if any(t in state['revoked'] for t in targets): return 'REVOKED'
        if identity in state['quarantined'] or any(state['sources'].get(s['source_id']) != s for s in summary['sources']): return 'QUARANTINED'
        evaluation = state['evaluations'].get(identity)
        if evaluation and (not evaluation['valid'] or evaluation['epoch'] != state['epoch']): return 'QUARANTINED'
        if any(p['source_id'] in {s['source_id'] for s in summary['sources']} for p in state['pending'].values()): return 'QUARANTINED'
        reviews = state['reviews'].get(identity, [])
        if len(reviews) > 1: return 'QUARANTINED'
        if reviews and (not reviews[0]['approved'] or reviews[0]['epoch'] != state['epoch']
                        or datetime.fromisoformat(reviews[0]['expires_at']) <= now): return 'QUARANTINED'
        if grant: return 'ADMITTED'
        return 'REVIEWED' if reviews else 'PROVISIONAL'

    def _after_commit(self, receipt):
        pass  # Deterministic lost-acknowledgement injection point; no background work.

    def _run(self, operation_id, action, payload, token, role, apply):
        if self._fatal:
            raise PermissionError('Coordinator process held after uncertain write; restart/recovery required')
        actor = self._principal(action, token, role)
        request_sha = digest({'action': action, 'payload': payload, 'actor': actor.principal_id})
        denial = None
        try:
            with closing(self.store.connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                authority, events = self.store.events(db)
                state = self._fold(events)
                require(state['epoch'] == self.epoch, 'STALE_COORDINATOR_INSTANCE')
                previous = next((e for e in events if e['operation_id'] == operation_id), None)
                if previous:
                    require(previous['request_sha256'] == request_sha, 'OPERATION_ID_CONFLICT')
                    require(action != 'QUALIFIED_READ', 'USE_ID_ALREADY_CONSUMED; historical lookup is not permission')
                    db.execute('ROLLBACK')
                    return CommitReceipt(authority_id=authority, operation_id=operation_id, event_action=previous['action'],
                        sequence=previous['sequence'], sha256=previous['event_sha256'])
                now = self._now()
                db.execute('SAVEPOINT candidate')
                try:
                    result = apply(db, state, actor, now)
                    db.execute('RELEASE candidate')
                    final_action = action
                except AdmissionRejected as exc:
                    db.execute('ROLLBACK TO candidate')
                    db.execute('RELEASE candidate')
                    denial = exc
                    result, final_action = {'attempted_action': action, 'reason': str(exc), 'payload_sha256': digest(payload)}, 'DENIED'
                receipt = self.store.append(db, operation_id=operation_id, request_sha256=request_sha,
                    action=final_action, actor=actor.model_dump(mode='json'), timestamp=now, payload=result)
                db.execute('COMMIT')
            self._after_commit(receipt)
        except AdmissionRejected:
            raise
        except BaseException:
            self._fatal = True
            raise
        if denial: raise denial
        return receipt

    def recover(self, operation_id, *, anchor, token, reason=None):
        anchor = Checkpoint.model_validate(anchor.model_dump(mode='json'))
        def apply(db, state, actor, now):
            require(isinstance(reason, str) and bool(reason.strip()), 'RECOVERY_REASON_REQUIRED')
            authority, events = self.store.events(db)
            require(anchor.authority_id == authority and anchor.sequence <= len(events)
                    and events[anchor.sequence - 1]['event_sha256'] == anchor.sha256
                    and anchor.epoch == sum(e['action'] == 'BOOT' for e in events[:anchor.sequence]), 'EXTERNAL_CHECKPOINT_MISMATCH')
            require(not state['pending'], 'UNRESOLVED_SOURCE_MUTATION')
            return {'anchor': anchor.model_dump(mode='json'), 'epoch': state['epoch'], 'reason': reason}
        return self._run(operation_id, 'RECOVER', {'anchor': anchor.model_dump(mode='json'), 'reason': reason}, token, 'recovery', apply)

    def register_source(self, operation_id, source, *, token):
        source = SourceVersion.model_validate(source.model_dump(mode='json'))
        def apply(db, state, actor, now):
            require(state['serving'], 'STARTUP_HOLD')
            require(source.source_id not in state['sources'] or state['sources'][source.source_id] == source.model_dump(mode='json'), 'SOURCE_INSTANCE_OR_GENERATION_CONFLICT')
            return source.model_dump(mode='json')
        return self._run(operation_id, 'REGISTER_SOURCE', source.model_dump(mode='json'), token, 'source_operator', apply)

    def prepare_bundle(self, operation_id, bundle, *, token):
        bundle = AdmissionBundle.model_validate(bundle.model_dump(mode='json'))
        require(bundle.scope == 'synthetic_test', 'REAL_EVIDENCE_PROVISIONAL')
        def apply(db, state, actor, now):
            require(state['serving'] and not state['pending'], 'AUTHORITY_OR_SOURCE_HELD')
            require(actor.principal_id == bundle.prepared_by, 'PREPARER_IDENTITY_CONFLICT')
            require(len(state['bundles']) < MAX_BUNDLES and bundle.bundle_id not in state['bundles'], 'BUNDLE_ID_OR_BUDGET_CONFLICT')
            require(all(state['sources'].get(s.source_id) == s.model_dump(mode='json') for s in bundle.sources), 'UNREGISTERED_OR_STALE_SOURCE_VECTOR')
            require(len(canonical_json(bundle).encode()) <= 16 * 1024 * 1024, 'BUNDLE_BYTE_BUDGET')
            # Structural sealing only; evaluation remains a distinct operation.
            require(len({o.object_id for o in bundle.objects}) == len(bundle.objects), 'DUPLICATE_OBJECT_ID')
            for obj in bundle.objects:
                require(obj.scope == 'synthetic_test', 'REAL_OBJECT_PROVISIONAL')
                content = canonical_json(obj)
                prior = db.execute('SELECT content,sha256 FROM objects WHERE object_id=?', (obj.object_id,)).fetchone()
                require(prior is None or prior == (content, sha256(content.encode()).hexdigest()), 'IMMUTABLE_OBJECT_CONFLICT')
                if prior is None: db.execute('INSERT INTO objects VALUES (?,?,?)', (obj.object_id, content, sha256(content.encode()).hexdigest()))
            content = canonical_json(bundle)
            db.execute('INSERT INTO bundles VALUES (?,?,?)', (bundle.bundle_id, content, input_hash(bundle)))
            return dict(bundle_id=bundle.bundle_id, bundle_sha256=input_hash(bundle), prepared_by=bundle.prepared_by,
                sources=[s.model_dump(mode='json') for s in bundle.sources], fingerprints=[o.fingerprint() for o in bundle.objects], epoch=state['epoch'])
        return self._run(operation_id, 'PREPARE', {'bundle_sha256': input_hash(bundle)}, token, 'preparer', apply)

    def evaluate_bundle(self, operation_id, bundle_id, *, token):
        def apply(db, state, actor, now):
            bundle = self._bundle(db, bundle_id)
            try:
                validate_bundle(bundle)
                valid, reasons = True, []
            except (ValueError, KeyError, TypeError, StopIteration) as exc:
                valid, reasons = False, [str(exc)]
            return {'bundle_id': bundle_id, 'bundle_sha256': input_hash(bundle), 'valid': valid, 'reasons': reasons, 'epoch': state['epoch']}
        return self._run(operation_id, 'EVALUATE', {'bundle_id': bundle_id}, token, 'preparer', apply)

    def record_review(self, operation_id, review, *, token):
        review = ReviewRequest.model_validate(review.model_dump(mode='json'))
        def apply(db, state, actor, now):
            bundle = self._bundle(db, review.bundle_id)
            require(state['serving'] and not state['pending'], 'AUTHORITY_OR_SOURCE_HELD')
            require(actor.principal_id != bundle.prepared_by, 'SELF_APPROVAL_PROHIBITED')
            require(review.epoch == state['epoch'] and review.bundle_sha256 == input_hash(bundle) and review.expires_at > now, 'STALE_REVIEW')
            require(self._state(state, review.bundle_id, now) in ('PROVISIONAL', 'REVIEWED', 'ADMITTED'), 'BUNDLE_HELD_OR_REVOKED')
            require(state['evaluations'].get(review.bundle_id, {}).get('valid') is True, 'EVALUATION_REQUIRED')
            require(not any(r['review_id'] == review.review_id for rows in state['reviews'].values() for r in rows), 'REVIEW_ID_CONFLICT')
            return review.model_dump(mode='json')
        return self._run(operation_id, 'REVIEW', review.model_dump(mode='json'), token, 'reviewer', apply)

    def admit_bundle(self, operation_id, bundle_id, *, review_id, expected_epoch, token):
        payload = {'bundle_id': bundle_id, 'review_id': review_id, 'epoch': expected_epoch}
        def apply(db, state, actor, now):
            require(state['serving'] and not state['pending'] and expected_epoch == state['epoch'], 'AUTHORITY_SOURCE_OR_EPOCH_HELD')
            require(self._state(state, bundle_id, now) == 'REVIEWED', 'CURRENT_INDEPENDENT_REVIEW_REQUIRED')
            bundle = validate_bundle(self._bundle(db, bundle_id))
            reviews = state['reviews'].get(bundle_id, [])
            require(len(reviews) == 1 and reviews[0]['review_id'] == review_id and reviews[0]['approved'], 'CONFLICTING_OR_DENIED_REVIEW')
            require(actor.principal_id not in (bundle.prepared_by, reviews[0]['actor']), 'INDEPENDENT_ADMISSION_ROLE_REQUIRED')
            return payload | {'grant_id': operation_id, 'bundle_sha256': input_hash(bundle),
                'members': [{'ticker': o.metadata.ticker, 'snapshot_sha256': input_hash(o.snapshot)} for o in bundle.batch.observations]}
        return self._run(operation_id, 'ADMIT', payload, token, 'admitter', apply)

    def revoke(self, operation_id, target_kind, target_id, *, reason, token):
        require(target_kind in ('bundle', 'object', 'source', 'review', 'grant', 'policy'), 'UNSUPPORTED_REVOCATION_TARGET')
        require(isinstance(reason, str) and bool(reason.strip()), 'REVOCATION_REASON_REQUIRED')
        payload = {'target_kind': target_kind, 'target_id': target_id, 'reason': reason}
        def apply(db, state, actor, now):
            known = {'bundle': set(state['bundles']), 'object': {p for b in state['bundles'].values() for p in b['fingerprints']},
                'source': set(state['sources']), 'review': {r['review_id'] for rows in state['reviews'].values() for r in rows},
                'grant': {g['grant_id'] for g in state['grants'].values()}, 'policy': {'synthetic-policy-v1'}}
            require(target_id in known[target_kind], 'UNKNOWN_REVOCATION_TARGET')
            changed = dict(state)
            changed['revoked'] = state['revoked'] | {(target_kind, target_id)}
            return payload | {'affected_bundles': [b for b in state['bundles'] if self._state(changed, b, now) == 'REVOKED']}
        return self._run(operation_id, 'REVOKE', payload, token, 'revoker', apply)

    def quarantine(self, operation_id, bundle_id, *, reason, token):
        require(isinstance(reason, str) and bool(reason.strip()), 'QUARANTINE_REASON_REQUIRED')
        def apply(db, state, actor, now):
            require(bundle_id in state['bundles'], 'UNKNOWN_BUNDLE')
            return {'bundle_id': bundle_id, 'reason': reason}
        return self._run(operation_id, 'QUARANTINE', {'bundle_id': bundle_id, 'reason': reason}, token, 'revoker', apply)

    def qualified_read(self, operation_id, bundle_id, *, expected_epoch, token):
        def apply(db, state, actor, now):
            require(state['serving'] and expected_epoch == state['epoch'], 'AUTHORITY_HELD_OR_STALE_EPOCH')
            require(self._state(state, bundle_id, now) == 'ADMITTED', 'EVIDENCE_NOT_CURRENTLY_ADMITTED')
            validate_bundle(self._bundle(db, bundle_id))
            return {'bundle_id': bundle_id, 'bundle_sha256': state['bundles'][bundle_id]['bundle_sha256'],
                'purpose': 'USD_RESEARCH_SIGNALS', 'scope': 'synthetic_test', 'epoch': state['epoch']}
        # A receipt records one use linearized before later revocations. It is
        # inspection-only afterward, not a reusable offline capability.
        return self._run(operation_id, 'QUALIFIED_READ', {'bundle_id': bundle_id, 'epoch': expected_epoch}, token, 'reader', apply)

    def replay(self):
        with closing(self.store.connect()) as db:
            db.execute('BEGIN')
            authority, events = self.store.events(db)
            state = self._fold(events)
            now = self._now()
            for identity in state['bundles']:
                self._bundle(db, identity)
            return {'inspection_only': True, 'authority_id': authority, 'epoch': state['epoch'],
                'serving': state['serving'] and not self._fatal and state['epoch'] == self.epoch,
                'states': {b: self._state(state, b, now) for b in state['bundles']},
                'pending_mutations': state['pending'], 'events': events}

    def lookup_operation(self, operation_id):
        with closing(self.store.connect()) as db:
            db.execute('BEGIN')
            authority, events = self.store.events(db)
            event = next((e for e in events if e['operation_id'] == operation_id), None)
            if event is None: raise KeyError(operation_id)
            return CommitReceipt(authority_id=authority, operation_id=operation_id, event_action=event['action'],
                sequence=event['sequence'], sha256=event['event_sha256'])

    def begin_source_mutation(self, mutation_id, source_id, *, expected_generation, token):
        payload = {'source_id': source_id, 'expected_generation': expected_generation}
        def apply(db, state, actor, now):
            require(state['serving'] and source_id in state['sources'], 'SOURCE_OR_AUTHORITY_UNAVAILABLE')
            source = state['sources'][source_id]
            require(source['generation'] == expected_generation and not any(p['source_id'] == source_id for p in state['pending'].values()), 'SOURCE_MUTATION_CONFLICT')
            return payload | {'instance_id': source['instance_id'], 'epoch': state['epoch']}
        return self._run(mutation_id, 'BEGIN_MUTATION', payload, token, 'source_operator', apply)

    def pending_fence(self, receipt, *, recovery=False):
        with closing(self.store.connect()) as db:
            db.execute('BEGIN')
            authority, events = self.store.events(db)
            state = self._fold(events)
            require(state['epoch'] == self.epoch and not self._fatal, 'STALE_COORDINATOR_INSTANCE')
            pending = state['pending'].get(receipt.operation_id)
            require(receipt.authority_id == authority and pending is not None
                and pending['receipt_sha256'] == receipt.sha256 and pending['receipt_sequence'] == receipt.sequence, 'MISSING_OR_WRONG_SOURCE_FENCE')
            require(recovery or pending['epoch'] == state['epoch'], 'PRE_RESTART_FENCE_REQUIRES_RECOVERY')
            return pending | {'authority_id': authority}

    def finish_source_mutation(self, operation_id, fence, participant, *, token):
        receipt = participant.load_receipt(fence.operation_id)
        payload = {'mutation_id': fence.operation_id, 'participant_sha256': digest(receipt)}
        def apply(db, state, actor, now):
            pending = state['pending'].get(fence.operation_id)
            require(pending is not None and pending['receipt_sha256'] == fence.sha256, 'MISSING_SOURCE_FENCE')
            require(fence.authority_id == self.store.events(db)[0]
                and receipt['authority_id'] == fence.authority_id and receipt['fence_sha256'] == fence.sha256
                and receipt['source_id'] == pending['source_id'] and receipt['instance_id'] == pending['instance_id']
                and receipt['old_generation'] == pending['expected_generation'], 'PARTICIPANT_RECEIPT_CONFLICT')
            require(receipt['status'] == 'APPLIED', 'SOURCE_NOT_APPLIED')
            source = SourceVersion(source_id=receipt['source_id'], instance_id=receipt['instance_id'], generation=receipt['new_generation'])
            return payload | {'source': source.model_dump(mode='json')}
        return self._run(operation_id, 'FINISH_MUTATION', payload, token, 'source_operator', apply)

    def abort_source_mutation(self, operation_id, fence, participant, *, token, reason=None):
        receipt = participant.load_receipt(fence.operation_id)
        def apply(db, state, actor, now):
            require(isinstance(reason, str) and bool(reason.strip()), 'RECOVERY_REASON_REQUIRED')
            pending = state['pending'].get(fence.operation_id)
            require(pending is not None and pending['receipt_sha256'] == fence.sha256, 'MISSING_SOURCE_FENCE')
            require(fence.authority_id == self.store.events(db)[0]
                and receipt['status'] == 'ABORTED' and receipt['source_id'] == pending['source_id']
                and receipt['instance_id'] == pending['instance_id'] and receipt['fence_sha256'] == fence.sha256
                and receipt['authority_id'] == fence.authority_id and receipt['old_generation'] == pending['expected_generation'], 'ABORT_RECEIPT_CONFLICT')
            return {'mutation_id': fence.operation_id, 'participant_sha256': digest(receipt), 'reason': reason}
        return self._run(operation_id, 'ABORT_MUTATION', {'mutation_id': fence.operation_id, 'receipt': digest(receipt), 'reason': reason}, token, 'recovery', apply)
