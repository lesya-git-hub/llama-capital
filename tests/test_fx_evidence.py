"""Invented offline FX publications only. No provider, portfolio or order calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_UP
from hashlib import sha256
import json
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

from models.fx_evidence import (FXReceipt, FXRecord, FXManifest, FXMapping, FXPolicy,
    FXEvaluationRequest, FXEvaluation, FXSnapshot)
from providers.provisional_fx_evidence import normalize_fx, decode
from tools.fx_evidence_store import FXEvidenceArchive, generation
from tools.fx_evidence_evaluator import evaluate_fx, evaluate_snapshot, replay_fx, UNIVERSE
from tools.historical_snapshot import input_hash, canonical_json

UTC = timezone.utc
DAY = date(2026, 3, 10)  # US/Europe DST mismatch week; all times INVENTED.
DECISION = datetime(2026, 3, 10, 20, tzinfo=UTC)
EARLY = datetime(2026, 3, 10, 12, tzinfo=UTC)
PUBLISHED = datetime(2026, 3, 10, 15, tzinfo=UTC)
ACQUIRED = datetime(2026, 3, 10, 15, 1, tzinfo=UTC)


def record(identity, kind, body, *, at=EARLY, publication=None, previous=None, logical=None,
           provider='INVENTED', **changes):
    raw = body if isinstance(body, bytes) else json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    metadata = dict(observation_id=identity, version='fixture-1', logical_key=logical or identity,
        previous_id=previous, provider_id=provider, dataset_id='INVENTED-REFERENCE', feed='INVENTED-DAILY',
        source_instance='MOCK-INSTANCE', source_generation='mock-1', release_id='release:' + identity,
        acquired_start=at, acquired_end=at, published_at=publication or at, clock_id='clock', uncertainty_ms=0,
        provenance='INVENTED ONLY; NO PROVIDER CLAIM', licensing_reference='license', response_status=200,
        page_count=1, complete=True, query_identity='offline-fixture:' + identity, raw_sha256=sha256(raw).hexdigest())
    metadata.update(changes)
    return FXRecord(kind=kind, receipt=FXReceipt(**metadata), body_b64=base64.b64encode(raw).decode())


def fixtures(*, reverse=False):
    documents = [record(name, 'document', dict(synthetic=True, purpose=purpose, provider_id='INVENTED', text='INVENTED TEST EVIDENCE'))
        for name, purpose in [('method', 'methodology'), ('corrections', 'correction_policy'), ('license', 'license'),
            ('clock', 'clock'), ('schedule', 'schedule'), ('closed', 'exception')]]
    series = dict(provider_id='INVENTED', dataset_id='INVENTED-REFERENCE', feed='INVENTED-DAILY',
        base='EUR' if reverse else 'USD', quote='USD' if reverse else 'EUR',
        direction='USD_PER_EUR' if reverse else 'EUR_PER_USD', operation='explicit_reciprocal' if reverse else 'direct',
        units='quote_per_one_base', rate_kind='official_reference', adjustment='NONE',
        methodology_version='INVENTED-1', methodology_ref='method', correction_policy_ref='corrections',
        license_ref='license', clock_ref='clock', calendar_id='calendar', timezone='Europe/Berlin',
        source_precision=24, source_rounding='INVENTED: exact decimal text', original_symbol='INVENTED ONLY')
    calendar = dict(provider_id='INVENTED', calendar_id='calendar', timezone='Europe/Berlin',
        coverage_start='2026-03-09', coverage_end='2026-03-15', schedule_ref='schedule',
        days=[dict(date=(DAY + timedelta(days=i)).isoformat(), publication_expected=i < 4,
                   exception_ref=None if i < 4 else 'closed') for i in range(-1, 6)])
    raw = dict(provider_id='INVENTED', dataset_id='INVENTED-REFERENCE', feed='INVENTED-DAILY', release_id='release:raw',
        base=series['base'], quote=series['quote'], direction=series['direction'], units='quote_per_one_base',
        rate_kind='official_reference', reference_date=DAY.isoformat(), effective_at='2026-03-10T14:00:00+00:00',
        published_at=PUBLISHED.isoformat(), rate='1.25' if reverse else '0.9200')
    artifact = record('release-proof', 'document', dict(synthetic=True, purpose='publication', provider_id='INVENTED', text='INVENTED RELEASE CONFIRMATION'), at=ACQUIRED)
    observation = record('raw', 'raw', raw, at=ACQUIRED, publication=PUBLISHED, logical='rate:2026-03-10')
    claim = dict(raw_id='raw', raw_sha256=observation.receipt.raw_sha256, raw_record_sha256=input_hash(observation), release_id='release:raw',
        series_id='series', confirmed=True, complete=True, claim='published_release_confirmed', publication_artifact_ref='release-proof')
    return [*documents, record('series', 'series', series), record('calendar', 'calendar', calendar),
            observation, artifact, record('publication', 'publication', claim, at=ACQUIRED)]


def archive(tmp_path, records=None):
    store = FXEvidenceArchive(tmp_path / 'fx.sqlite', create=True)
    for r in records if records is not None else fixtures(): store.record(r)
    return store


def request(store, *, identity='eval', **changes):
    manifest = FXManifest(manifest_id='plan', series_id='series', raw_ids=('raw',), expected_dates=(DAY,),
        mappings=tuple(FXMapping(ticker=t, reference_date=DAY, raw_id='raw') for t in UNIVERSE))
    return FXEvaluationRequest(**(dict(evaluation_id=identity, manifest=manifest,
        policy=FXPolicy(version='SYNTHETIC-1', max_age_seconds=86400), decision_at=DECISION,
        evidence_cutoff=DECISION, expected_generation=store.snapshot().generation) | changes))


def replace_record(records, identity, *, body=None, **metadata):
    result = []
    for r in records:
        if r.receipt.observation_id != identity:
            result.append(r); continue
        raw = r.body() if body is None else body if isinstance(body, bytes) else json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        receipt = r.receipt.model_copy(update={'raw_sha256': sha256(raw).hexdigest(), **metadata})
        result.append(r.model_copy(update={'receipt': receipt, 'body_b64': base64.b64encode(raw).decode()}))
    return result


@pytest.mark.parametrize('reverse,expected', [(False, '0.92'), (True, '0.8')])
def test_positive_independent_checks_immutable_replay_and_isolation(tmp_path, reverse, expected):
    store = archive(tmp_path, fixtures(reverse=reverse))
    before = store.snapshot()
    result = evaluate_fx(store, request(store))
    assert result.status == 'ELIGIBLE_FOR_SYNTHETIC_REVIEW' and not result.reasons
    assert result.numerical_valid and result.publication_valid and result.calendar_valid and result.temporal_valid and result.history_valid
    assert result.rates[0].canonical_direction == 'EUR_PER_USD'
    assert Decimal(result.rates[0].canonical_rate_text) == Decimal(expected)
    assert result.rates[0].original_rate_text == ('1.25' if reverse else '0.9200')
    assert all(r.receipt.status == 'PROVISIONAL' for r in store.snapshot().records)
    assert store.snapshot() == before and result.inspection_only
    with localcontext() as ctx:
        ctx.prec = 3; ctx.rounding = ROUND_UP
        assert replay_fx(result, expected_hash=input_hash(result)) == result
    reopened = FXEvidenceArchive(store.path)
    assert reopened.load_evaluation('eval', expected_hash=input_hash(result)) == result
    assert FXEvaluation.model_validate_json(canonical_json(result)) == result
    from tools.fx_conversion import FXTrustRegistry
    from tools.market_verification import TrustRegistry
    assert FXTrustRegistry().pins == TrustRegistry().pins == ()


@pytest.mark.parametrize('change', [dict(base='EUR'), dict(direction='USD_PER_EUR'), dict(units='USD/EUR'),
    dict(rate_kind='bid'), dict(rate_kind='indicative_mid'), dict(base='GBP'), dict(rate=0.92),
    dict(rate=True), dict(rate='0'), dict(rate='-1'), dict(rate='NaN'), dict(rate='Infinity'),
    dict(rate='1e-2'), dict(rate='0.' + '1' * 25)])
def test_ambiguous_inverted_unsupported_or_nondecimal_rates(tmp_path, change):
    records = fixtures(); raw = decode(next(r for r in records if r.kind == 'raw'))
    records = replace_record(records, 'raw', body=raw | change)
    store = archive(tmp_path, records)
    result = evaluate_fx(store, request(store))
    assert result.status == 'HELD' and not result.numerical_valid


@pytest.mark.parametrize('missing', ['publication', 'release-proof', 'calendar', 'schedule', 'license', 'clock'])
def test_missing_evidence_never_replaced_by_hash_or_delay(tmp_path, missing):
    store = archive(tmp_path, [r for r in fixtures() if r.receipt.observation_id != missing])
    result = evaluate_fx(store, request(store))
    assert result.status == 'HELD'
    if missing in ('publication', 'release-proof'): assert result.numerical_valid and not result.publication_valid
    if missing in ('calendar', 'schedule'): assert result.numerical_valid and result.publication_valid and not result.calendar_valid


@pytest.mark.parametrize('field,value', [('effective_at', '2026-03-09T14:00:00+00:00'),
    ('effective_at', '2026-03-10T21:00:00+00:00'), ('published_at', '2026-03-10T21:00:00+00:00'),
    ('published_at', '2026-03-10'), ('published_at', '2026-03-10T15:00:00'),
    ('effective_at', 1770000000), ('published_at', None)])
def test_timestamp_manipulation(tmp_path, field, value):
    records = fixtures(); raw = decode(next(r for r in records if r.kind == 'raw'))
    store = archive(tmp_path, replace_record(records, 'raw', body=raw | {field: value}))
    result = evaluate_fx(store, request(store))
    assert result.status == 'HELD' and not result.temporal_valid


def test_stale_rate_and_fresh_download_cannot_refresh_it(tmp_path):
    store = archive(tmp_path)
    req = request(store, policy=FXPolicy(version='strict', max_age_seconds=10))
    result = evaluate_fx(store, req)
    assert not result.temporal_valid and result.status == 'HELD'


@pytest.mark.parametrize('adjustment,eligible', [(0, True), (1, False)])
def test_acquisition_clock_uncertainty_boundary(tmp_path, adjustment, eligible):
    records = replace_record(fixtures(), 'raw', uncertainty_ms=adjustment)
    store = archive(tmp_path, records)
    result = evaluate_fx(store, request(store, evidence_cutoff=ACQUIRED))
    assert (result.status == 'ELIGIBLE_FOR_SYNTHETIC_REVIEW') == eligible


def test_backfill_and_future_evidence_cutoff_not_as_known_history(tmp_path):
    store = archive(tmp_path)
    result = evaluate_fx(store, request(store, decision_at=PUBLISHED, evidence_cutoff=DECISION))
    assert result.status == 'HELD' and 'EVIDENCE_CUTOFF_LOOKAHEAD' in result.reasons


def test_missing_publication_timestamp_preserved_but_held(tmp_path):
    store = archive(tmp_path, replace_record(fixtures(), 'raw', published_at=None))
    result = evaluate_fx(store, request(store))
    assert result.numerical_valid and not result.publication_valid and not result.temporal_valid


@pytest.mark.parametrize('change', [dict(evidence_cutoff=1770000000), dict(decision_at='2026-03-10T20:00:00'),
    dict(scope='real'), dict(status='ADMITTED')])
def test_unauthorized_or_ambiguous_model_states(tmp_path, change):
    store = archive(tmp_path)
    with pytest.raises(ValueError): request(store, **change)


def test_duplicate_keys_and_corrupt_payloads(tmp_path):
    store = archive(tmp_path, replace_record(fixtures(), 'raw', body=b'{"rate":"1","rate":"2"}'))
    result = evaluate_fx(store, request(store))
    assert result.status == 'HELD' and not result.numerical_valid


def correction(original, *, identity='corrected', previous='raw', provider='INVENTED', at=ACQUIRED + timedelta(minutes=2)):
    body = decode(original) | {'rate': '0.93', 'release_id': 'release:' + identity, 'provider_id': provider}
    return record(identity, 'raw', body, logical=original.receipt.logical_key, previous=previous,
        provider=provider, at=at, publication=PUBLISHED)


def test_revision_retained_old_replay_unchanged_new_evaluation_held(tmp_path):
    store = archive(tmp_path)
    old = evaluate_fx(store, request(store))
    store.record(correction(next(r for r in store.snapshot().records if r.kind == 'raw')))
    current = evaluate_fx(store, request(store, identity='new-eval'))
    assert current.status == 'HELD' and not current.history_valid
    assert replay_fx(old, expected_hash=input_hash(old)) == old
    assert store.load_evaluation('eval', expected_hash=input_hash(old)) == old
    assert len([r for r in store.snapshot().records if r.kind == 'raw']) == 2


@pytest.mark.parametrize('provider', ['INVENTED', 'OTHER-INVENTED'])
def test_conflicting_sources_or_new_ids_cannot_be_omitted(tmp_path, provider):
    store = archive(tmp_path)
    raw = next(r for r in store.snapshot().records if r.kind == 'raw')
    store.record(correction(raw, identity='conflict', previous=None, provider=provider))
    result = evaluate_fx(store, request(store))
    assert result.status == 'HELD' and not result.history_valid


def test_missing_predecessor_cannot_create_finality(tmp_path):
    store = archive(tmp_path)
    raw = next(r for r in store.snapshot().records if r.kind == 'raw')
    store.record(correction(raw, previous='missing'))
    result = evaluate_fx(store, request(store))
    assert not result.history_valid


def test_incomplete_six_stock_plan_and_manifest(tmp_path):
    store = archive(tmp_path)
    req = request(store)
    manifest = req.manifest.model_copy(update={'mappings': req.manifest.mappings[:-1]})
    result = evaluate_fx(store, req.model_copy(update={'manifest': manifest}))
    assert result.status == 'HELD' and 'INCOMPLETE_SIX_STOCK_FX_COVERAGE_PLAN' in result.reasons


@pytest.mark.parametrize('change', [dict(complete=False), dict(response_status=503)])
def test_partial_failed_response_never_complete(tmp_path, change):
    store = archive(tmp_path, replace_record(fixtures(), 'raw', **change))
    assert evaluate_fx(store, request(store)).status == 'HELD'


def test_identity_immutable_and_identical_retry_idempotent(tmp_path):
    store = archive(tmp_path); before = store.snapshot()
    raw = next(r for r in before.records if r.kind == 'raw')
    assert store.record(raw) == input_hash(raw) and store.snapshot() == before
    with pytest.raises(ValueError, match='IMMUTABLE'):
        store.record(raw.model_copy(update={'receipt': raw.receipt.model_copy(update={'provenance': 'changed'})}))
    assert store.snapshot() == before


def test_raw_hash_mismatch_never_persisted(tmp_path):
    store = archive(tmp_path); before = store.snapshot()
    raw = next(r for r in before.records if r.kind == 'raw')
    with pytest.raises(ValueError): store.record(raw.model_copy(update={'body_b64': base64.b64encode(b'corrupt').decode()}))
    assert store.snapshot() == before


@pytest.mark.parametrize('tamper', ['content', 'tail', 'schema'])
def test_archive_corruption_fails_closed_without_repair(tmp_path, tamper):
    store = archive(tmp_path)
    with closing(store.connect()) as db:
        if tamper == 'content': db.execute("UPDATE events SET content='{}' WHERE seq=1")
        elif tamper == 'tail': db.execute('DELETE FROM events WHERE seq=(SELECT MAX(seq) FROM events)')
        else: db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError): store.snapshot()
    with pytest.raises(ValueError): FXEvidenceArchive(store.path)


def test_interrupted_append_rolls_back_and_lost_ack_recovers(tmp_path, monkeypatch):
    store = archive(tmp_path); before = store.snapshot()
    r = correction(next(r for r in before.records if r.kind == 'raw'))
    def crash(kind): raise RuntimeError('injected')
    monkeypatch.setattr(store, '_before_commit', crash)
    with pytest.raises(RuntimeError): store.record(r)
    assert store.snapshot() == before
    monkeypatch.undo(); monkeypatch.setattr(store, '_after_commit', crash)
    with pytest.raises(RuntimeError): store.record(r)
    monkeypatch.undo()
    assert r in FXEvidenceArchive(store.path).snapshot().records
    assert store.record(r) == input_hash(r)


def test_generation_checked_inside_evaluation_commit(tmp_path, monkeypatch):
    store = archive(tmp_path); req = request(store)
    result = evaluate_snapshot(store.snapshot(), req)
    store.record(correction(next(r for r in store.snapshot().records if r.kind == 'raw')))
    with pytest.raises(ValueError, match='SOURCE_CHANGED'): store.save_evaluation(result)
    with pytest.raises(ValueError): store.load_evaluation('eval', expected_hash=input_hash(result))


def test_competing_revision_writers_are_retained_and_held(tmp_path):
    store = archive(tmp_path)
    raw = next(r for r in store.snapshot().records if r.kind == 'raw')
    barrier = Barrier(2)
    def write(i):
        barrier.wait(); return store.record(correction(raw, identity='revision-' + str(i)))
    with ThreadPoolExecutor(2) as pool: assert len(list(pool.map(write, [1, 2]))) == 2
    result = evaluate_fx(store, request(store))
    assert not result.history_valid and result.status == 'HELD'


def test_abrupt_process_exit_does_not_publish_partial_history(tmp_path):
    store = archive(tmp_path); before = store.snapshot()
    script = "import sqlite3,sys,os; d=sqlite3.connect(sys.argv[1],isolation_level=None); d.execute('BEGIN IMMEDIATE'); d.execute('DELETE FROM events'); os._exit(42)"
    assert subprocess.run([sys.executable, '-c', script, str(store.path)], check=False, timeout=15).returncode == 42
    assert FXEvidenceArchive(store.path).snapshot() == before


def test_replay_tampering_or_environment_change_rejected(tmp_path, monkeypatch):
    store = archive(tmp_path); result = evaluate_fx(store, request(store))
    changed = result.model_copy(update={'status': 'HELD'})
    with pytest.raises(ValueError): replay_fx(changed, expected_hash=input_hash(changed))
    import tools.fx_evidence_evaluator as module
    monkeypatch.setattr(module, 'engine_hash', lambda: 'changed')
    with pytest.raises(ValueError): replay_fx(result, expected_hash=input_hash(result))


def test_missing_archive_not_recreated(tmp_path):
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError): FXEvidenceArchive(path)
    assert not path.exists()


def test_explicit_corrected_release_requires_new_evaluation_and_proof(tmp_path):
    store = archive(tmp_path)
    old = evaluate_fx(store, request(store))
    raw = next(r for r in store.snapshot().records if r.kind == 'raw')
    corrected = correction(raw)
    store.record(corrected)
    claim = dict(raw_id='corrected', raw_sha256=corrected.receipt.raw_sha256,
        raw_record_sha256=input_hash(corrected), release_id=corrected.receipt.release_id, series_id='series',
        confirmed=True, complete=True, claim='published_release_confirmed', publication_artifact_ref='release-proof')
    store.record(record('corrected-publication', 'publication', claim, at=ACQUIRED + timedelta(minutes=3),
        previous='publication', logical='publication'))
    req = request(store, identity='corrected-evaluation')
    manifest = req.manifest.model_copy(update={'raw_ids': ('corrected',), 'mappings': tuple(
        m.model_copy(update={'raw_id': 'corrected'}) for m in req.manifest.mappings)})
    fresh = evaluate_fx(store, req.model_copy(update={'manifest': manifest}))
    assert fresh.status == 'ELIGIBLE_FOR_SYNTHETIC_REVIEW'
    assert fresh.rates[0].original_rate_text == '0.93'
    assert store.load_evaluation('eval', expected_hash=input_hash(old)) == old
    assert replay_fx(old, expected_hash=input_hash(old)) == old


def test_later_correction_cannot_rewrite_as_known_cutoff(tmp_path):
    store = archive(tmp_path)
    old = evaluate_fx(store, request(store, evidence_cutoff=ACQUIRED))
    store.record(correction(next(r for r in store.snapshot().records if r.kind == 'raw')))
    historical = evaluate_fx(store, request(store, identity='historical', evidence_cutoff=ACQUIRED))
    assert old.status == historical.status == 'ELIGIBLE_FOR_SYNTHETIC_REVIEW'
    assert old.rates == historical.rates


@pytest.mark.parametrize('change', [dict(raw_sha256='0' * 64), dict(raw_record_sha256='0' * 64),
    dict(confirmed=False), dict(complete=False), dict(release_id='wrong')])
def test_publication_claim_binds_entire_observation(tmp_path, change):
    records = fixtures(); claim = decode(next(r for r in records if r.kind == 'publication'))
    store = archive(tmp_path, replace_record(records, 'publication', body=claim | change))
    result = evaluate_fx(store, request(store))
    assert result.numerical_valid and result.calendar_valid and not result.publication_valid
    assert result.status == 'HELD'


def test_publisher_holiday_is_independent_of_release_and_number(tmp_path):
    records = fixtures(); calendar = decode(next(r for r in records if r.kind == 'calendar'))
    calendar['days'] = [d | dict(publication_expected=False, exception_ref='closed')
        if d['date'] == DAY.isoformat() else d for d in calendar['days']]
    store = archive(tmp_path, replace_record(records, 'calendar', body=calendar))
    result = evaluate_fx(store, request(store))
    assert result.numerical_valid and result.publication_valid and not result.calendar_valid


@pytest.mark.parametrize('days', [1, 4, 5])
def test_no_weekend_or_missing_release_carry(tmp_path, days):
    store = archive(tmp_path)
    result = evaluate_fx(store, request(store, decision_at=DECISION + timedelta(days=days),
        evidence_cutoff=DECISION + timedelta(days=days), policy=FXPolicy(version='long-age', max_age_seconds=999999)))
    assert result.status == 'HELD' and not result.temporal_valid


def test_early_us_close_cannot_use_later_european_release(tmp_path):
    store = archive(tmp_path)
    earlier = datetime(2026, 3, 10, 14, 30, tzinfo=UTC)
    result = evaluate_fx(store, request(store, decision_at=earlier, evidence_cutoff=earlier))
    assert result.status == 'HELD' and not result.temporal_valid


def test_equivalent_utc_decision_offsets_preserve_identity(tmp_path):
    store = archive(tmp_path); req = request(store)
    other = req.model_copy(update={'decision_at': DECISION.astimezone(timezone(timedelta(hours=2)))})
    assert evaluate_snapshot(store.snapshot(), req) == evaluate_snapshot(store.snapshot(), other)


def test_evaluation_audit_failure_rolls_back_complete_result(tmp_path, monkeypatch):
    store = archive(tmp_path); req = request(store)
    expected = evaluate_snapshot(store.snapshot(), req)
    def fail(kind): raise sqlite3.OperationalError('injected full disk')
    monkeypatch.setattr(store, '_before_commit', fail)
    with pytest.raises(sqlite3.OperationalError): evaluate_fx(store, req)
    with pytest.raises(ValueError): store.load_evaluation('eval', expected_hash=input_hash(expected))


def test_current_coordinator_still_refuses_fx_and_risk_real_scope(tmp_path):
    from models.evidence_admission import AdmissionBundle
    from tools.fx_conversion import FXQuote
    # Existing literals cannot be widened by a new evidence status.
    with pytest.raises(ValueError): FXReceipt.model_validate(fixtures()[0].receipt.model_dump(mode='json') | {'scope': 'real'})
    with pytest.raises(ValueError): FXQuote.model_validate({'scope': 'ADMITTED', 'rate_kind': 'official_reference'})
    assert AdmissionBundle.model_fields['fx_status'].annotation.__args__ == ('FX_NOT_INCLUDED',)


def test_recurring_reciprocal_independent_of_caller_context():
    from models.fx_evidence import FXSeries
    records = fixtures(reverse=True)
    series_record = next(r for r in records if r.kind == 'series')
    series = FXSeries.model_validate(decode(series_record))
    original = next(r for r in records if r.kind == 'raw')
    modified = next(r for r in replace_record([original], 'raw', body=decode(original) | {'rate': '3'}))
    normal = normalize_fx(modified, series, series_sha256=input_hash(series_record))
    with localcontext() as ctx:
        ctx.prec = 3; ctx.rounding = ROUND_UP
        assert normalize_fx(modified, series, series_sha256=input_hash(series_record)) == normal
    assert normal.canonical_rate_text == '0.' + '3' * 80
    assert normal.original_rate_text == '3'


def test_omitted_conflicting_calendar_cannot_be_selected_around(tmp_path):
    store = archive(tmp_path)
    calendar = decode(next(r for r in store.snapshot().records if r.kind == 'calendar'))
    calendar['days'][1] |= dict(publication_expected=False, exception_ref='closed')
    store.record(record('competing-calendar', 'calendar', calendar))
    result = evaluate_fx(store, request(store))
    assert result.numerical_valid and result.publication_valid and not result.calendar_valid


def test_omitted_conflicting_series_cannot_change_direction(tmp_path):
    store = archive(tmp_path)
    series = decode(next(r for r in store.snapshot().records if r.kind == 'series'))
    store.record(record('competing-series', 'series', series | {'operation': 'explicit_reciprocal'}))
    assert evaluate_fx(store, request(store)).status == 'HELD'


def test_duplicate_evaluation_id_cannot_overwrite_history(tmp_path):
    store = archive(tmp_path)
    old = evaluate_fx(store, request(store))
    assert evaluate_fx(store, request(store)) == old
    with pytest.raises(ValueError, match='IMMUTABLE'):
        evaluate_fx(store, request(store, policy=FXPolicy(version='different', max_age_seconds=1)))
    assert store.load_evaluation('eval', expected_hash=input_hash(old)) == old


def test_dst_gap_naive_wall_time_is_rejected(tmp_path):
    records = fixtures(); raw = decode(next(r for r in records if r.kind == 'raw'))
    store = archive(tmp_path, replace_record(records, 'raw', body=raw | {'effective_at': '2026-03-29T02:30:00'}))
    result = evaluate_fx(store, request(store))
    assert not result.temporal_valid and result.status == 'HELD'


def test_record_budget_failure_does_not_poison_archive(tmp_path, monkeypatch):
    import tools.fx_evidence_store as module
    store = archive(tmp_path); before = store.snapshot()
    raw = correction(next(r for r in before.records if r.kind == 'raw'))
    monkeypatch.setattr(module, 'MAX_JOURNAL_BYTES', sum(len(canonical_json(r).encode()) for r in before.records) + 1)
    with pytest.raises(ValueError, match='JOURNAL_BUDGET'): store.record(raw)
    assert store.snapshot() == before


@pytest.mark.parametrize('identity', ['publication', 'calendar', 'series', 'method'])
def test_every_supporting_receipt_requires_known_clock_evidence(tmp_path, identity):
    store = archive(tmp_path, replace_record(fixtures(), identity, clock_id='missing-clock'))
    assert evaluate_fx(store, request(store)).status == 'HELD'


def test_normalized_contract_does_not_accept_numeric_effective_time(tmp_path):
    from models.fx_evidence import FXNormalizedRate
    store = archive(tmp_path); result = evaluate_fx(store, request(store))
    with pytest.raises(ValueError):
        FXNormalizedRate.model_validate(result.rates[0].model_dump(mode='json') | {'effective_at': 1770000000})
