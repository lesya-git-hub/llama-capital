"""Pure synthetic FX eligibility and inspection replay; no admission integration."""
from datetime import date, timedelta
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import platform
from zoneinfo import ZoneInfo

from models.fx_evidence import (FXSeries, FXCalendar, FXPublication, FXEvaluation,
    FXEvaluationRequest, FXSnapshot)
from providers.provisional_fx_evidence import decode, numeric_fx, normalize_fx
from tools.fx_evidence_store import generation
from tools.historical_snapshot import input_hash

UNIVERSE = ('AAPL', 'JNJ', 'JPM', 'MSFT', 'WMT', 'XOM')


def engine_hash():
    root = Path(__file__).resolve().parents[1]
    h = sha256()
    for name in ('models/fx_evidence.py', 'providers/provisional_fx_evidence.py',
                 'tools/fx_evidence_store.py', 'tools/fx_evidence_evaluator.py', 'tools/historical_snapshot.py'):
        h.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    h.update((platform.python_version() + ':' + version('pydantic') + ':' + version('tzdata')).encode())
    return h.hexdigest()


def evaluate_snapshot(snapshot, request):
    snapshot = FXSnapshot.model_validate(snapshot.model_dump(mode='json'))
    request = FXEvaluationRequest.model_validate(request.model_dump(mode='json'))
    if generation(snapshot.records) != snapshot.generation or snapshot.generation != request.expected_generation:
        raise ValueError('FX_SNAPSHOT_GENERATION_MISMATCH')
    records = {r.receipt.observation_id: r for r in snapshot.records}
    if len(records) != len(snapshot.records):
        raise ValueError('DUPLICATE_FX_EVIDENCE_ID')
    # Check every body even when unavailable at the requested historical cutoff.
    for record in snapshot.records:
        if sha256(record.body()).hexdigest() != record.receipt.raw_sha256:
            raise ValueError('FX_SNAPSHOT_RAW_INTEGRITY')
    reasons, rates = set(), []
    flags = dict(numerical_valid=True, publication_valid=True, calendar_valid=True,
                 temporal_valid=True, history_valid=True)
    def fail(domain, reason):
        flags[domain] = False
        reasons.add(reason)
    def known(record):
        return record.receipt.acquired_end + timedelta(milliseconds=record.receipt.uncertainty_ms) <= request.evidence_cutoff
    available = {k: r for k, r in records.items() if known(r)}
    if request.evidence_cutoff > request.decision_at:
        fail('temporal_valid', 'EVIDENCE_CUTOFF_LOOKAHEAD')
    groups = {}
    for identity, record in available.items():
        r = record.receipt
        key = (record.kind, r.provider_id, r.dataset_id, r.feed, r.logical_key)
        groups.setdefault(key, []).append(identity)
        if r.previous_id is not None:
            previous = available.get(r.previous_id)
            if previous is None or (previous.kind, previous.receipt.provider_id, previous.receipt.dataset_id,
                    previous.receipt.feed, previous.receipt.logical_key) != key or previous.receipt.acquired_end > r.acquired_start:
                fail('history_valid', 'MISSING_OR_INVALID_FX_PREDECESSOR')
    heads = set()
    for identities in groups.values():
        superseded = {available[i].receipt.previous_id for i in identities}
        current = set(identities) - superseded
        if len(current) != 1:
            fail('history_valid', 'UNRESOLVED_FX_REVISION_FORK')
        heads.update(current)

    def resolve(identity, kind):
        record = available.get(identity)
        if record is None or record.kind != kind or identity not in heads:
            raise ValueError('MISSING_UNAVAILABLE_OR_SUPERSEDED_' + kind.upper())
        r = record.receipt
        if not r.complete or r.response_status != 200 or r.published_at is None or r.published_at > r.acquired_end or r.published_at > request.evidence_cutoff:
            raise ValueError('INCOMPLETE_OR_UNPUBLISHED_' + kind.upper())
        clock = available.get(r.clock_id)
        if clock is None or clock.kind != 'document' or r.clock_id not in heads:
            raise ValueError('MISSING_OR_SUPERSEDED_RECEIPT_CLOCK')
        evidence = decode(clock)
        if (evidence.get('synthetic') is not True or evidence.get('purpose') != 'clock'
                or not clock.receipt.complete or clock.receipt.response_status != 200
                or clock.receipt.published_at is None or clock.receipt.published_at > clock.receipt.acquired_end
                or clock.receipt.published_at > request.evidence_cutoff):
            raise ValueError('INVALID_RECEIPT_CLOCK_EVIDENCE')
        return record

    def document(identity, purpose, provider):
        r = resolve(identity, 'document')
        v = decode(r)
        if set(v) != {'synthetic', 'purpose', 'provider_id', 'text'} or v['synthetic'] is not True or v['purpose'] != purpose or v['provider_id'] != provider or r.receipt.provider_id != provider or not isinstance(v['text'], str) or not v['text'].strip():
            raise ValueError('MISSING_SYNTHETIC_' + purpose.upper() + '_EVIDENCE')
        return r

    manifest = request.manifest
    if not manifest.raw_ids or len(set(manifest.raw_ids)) != len(manifest.raw_ids) or not manifest.expected_dates or tuple(sorted(set(manifest.expected_dates))) != manifest.expected_dates:
        fail('numerical_valid', 'INCOMPLETE_OR_DUPLICATE_FX_MANIFEST')
    try:
        series_record = resolve(manifest.series_id, 'series')
        series = FXSeries.model_validate(decode(series_record))
        if (series.provider_id, series.dataset_id, series.feed) != (series_record.receipt.provider_id, series_record.receipt.dataset_id, series_record.receipt.feed):
            raise ValueError('SERIES_SOURCE_CONFLICT')
        ZoneInfo(series.timezone)
        for ref, purpose in ((series.methodology_ref, 'methodology'), (series.correction_policy_ref, 'correction_policy'),
                             (series.license_ref, 'license'), (series.clock_ref, 'clock')):
            document(ref, purpose, series.provider_id)
        for identity in sorted(heads):
            other = available[identity]
            if other.kind == 'series' and (other.receipt.provider_id, other.receipt.dataset_id, other.receipt.feed) == (series.provider_id, series.dataset_id, series.feed):
                if FXSeries.model_validate(decode(other)) != series:
                    raise ValueError('CONFLICTING_ACTIVE_FX_SERIES_DEFINITIONS')
    except (ValueError, KeyError, TypeError) as exc:
        fail('numerical_valid', 'SERIES_OR_DOCUMENT_REJECTED:' + str(exc))
        series = None

    calendar = None
    if series is not None:
        try:
            calendar_record = resolve(series.calendar_id, 'calendar')
            calendar = FXCalendar.model_validate(decode(calendar_record))
            if calendar.provider_id != series.provider_id or calendar_record.receipt.provider_id != series.provider_id or calendar.calendar_id != series.calendar_id or calendar.timezone != series.timezone:
                raise ValueError('FX_CALENDAR_IDENTITY_CONFLICT')
            ZoneInfo(calendar.timezone)
            dates = tuple(d.date for d in calendar.days)
            count = (calendar.coverage_end - calendar.coverage_start).days
            if not 0 <= count <= 3660 or dates != tuple(calendar.coverage_start + timedelta(days=i) for i in range(count + 1)):
                raise ValueError('INCOMPLETE_FX_CALENDAR_COVERAGE')
            document(calendar.schedule_ref, 'schedule', series.provider_id)
            for day in calendar.days:
                if not day.publication_expected:
                    document(day.exception_ref, 'exception', series.provider_id)
            target_day = request.decision_at.astimezone(ZoneInfo(series.timezone)).date()
            if not calendar.coverage_start <= target_day <= calendar.coverage_end:
                raise ValueError('FX_CALENDAR_DOES_NOT_REACH_DECISION')
            view = {d.date: d for d in calendar.days}
            for identity in sorted(heads):
                other_record = available[identity]
                if other_record.kind != 'calendar' or other_record.receipt.provider_id != series.provider_id:
                    continue
                other = FXCalendar.model_validate(decode(other_record))
                if max(calendar.coverage_start, other.coverage_start) <= min(calendar.coverage_end, other.coverage_end):
                    if other.timezone != calendar.timezone or any(view[d.date] != d for d in other.days if d.date in view):
                        raise ValueError('CONFLICTING_OVERLAPPING_FX_CALENDAR')
        except (ValueError, KeyError, TypeError) as exc:
            fail('calendar_valid', 'CALENDAR_REJECTED:' + str(exc))
            calendar = None
    else:
        fail('calendar_valid', 'SERIES_REQUIRED_FOR_CALENDAR')

    selected_days, raw_dates = [], {}
    for identity in manifest.raw_ids:
        record = available.get(identity)
        if record is None or record.kind != 'raw':
            fail('temporal_valid', 'RAW_UNAVAILABLE_AT_CUTOFF:' + identity)
            fail('numerical_valid', 'RAW_REQUIRED:' + identity)
            fail('publication_valid', 'RAW_REQUIRED_FOR_PUBLICATION:' + identity)
            continue
        try:
            if series is None:
                raise ValueError('SERIES_REQUIRED')
            numeric, _ = numeric_fx(record, series)
            numeric_date = date.fromisoformat(numeric['reference_date'])
            selected_days.append(numeric_date)
            raw_dates[identity] = numeric_date
        except (ValueError, KeyError, TypeError) as exc:
            fail('numerical_valid', 'NUMERICAL_REJECTED:' + identity + ':' + str(exc))
        normalized = None
        try:
            if series is not None:
                normalized = normalize_fx(record, series, series_sha256=input_hash(series_record))
                rates.append(normalized)
                r = record.receipt
                if r.clock_id != series.clock_ref or r.licensing_reference != series.license_ref:
                    raise ValueError('CLOCK_OR_LICENSE_BINDING_CONFLICT')
                if not 0 <= (request.decision_at - normalized.effective_at).total_seconds() <= request.policy.max_age_seconds:
                    raise ValueError('STALE_OR_FUTURE_EFFECTIVE_RATE')
                if normalized.published_at > request.decision_at:
                    raise ValueError('PUBLICATION_LOOKAHEAD')
                if calendar is not None:
                    target_day = request.decision_at.astimezone(ZoneInfo(calendar.timezone)).date()
                    if normalized.reference_date != target_day:
                        raise ValueError('NO_CARRY_REFERENCE_DATE_MISMATCH')
                    if not any(d.date == normalized.reference_date and d.publication_expected for d in calendar.days):
                        fail('calendar_valid', 'NO_PUBLICATION_SESSION_FOR_RATE')
        except (ValueError, KeyError, TypeError) as exc:
            fail('temporal_valid', 'TEMPORAL_REJECTED:' + identity + ':' + str(exc))
        try:
            resolve(identity, 'raw')
            claims = []
            for key in sorted(heads):
                claim_record = available[key]
                if claim_record.kind != 'publication':
                    continue
                claim = FXPublication.model_validate(decode(claim_record))
                if claim.raw_id == identity:
                    resolve(key, 'publication')
                    claims.append((claim_record, claim))
            if len(claims) != 1:
                raise ValueError('EXACT_PUBLICATION_CONFIRMATION_REQUIRED')
            claim_record, claim = claims[0]
            if (not claim.confirmed or not claim.complete or claim.raw_sha256 != record.receipt.raw_sha256
                    or claim.raw_record_sha256 != input_hash(record)
                    or claim.release_id != record.receipt.release_id or claim.series_id != manifest.series_id
                    or claim_record.receipt.provider_id != record.receipt.provider_id
                    or record.receipt.published_at is None or claim_record.receipt.published_at < record.receipt.published_at):
                raise ValueError('PUBLICATION_BINDING_CONFLICT')
            document(claim.publication_artifact_ref, 'publication', record.receipt.provider_id)
        except (ValueError, KeyError, TypeError) as exc:
            fail('publication_valid', 'PUBLICATION_REJECTED:' + identity + ':' + str(exc))

    if tuple(sorted(selected_days)) != manifest.expected_dates:
        fail('numerical_valid', 'INCOMPLETE_EXPECTED_RATE_PERIODS')
    expected_mappings = {(ticker, day) for ticker in UNIVERSE for day in manifest.expected_dates}
    actual = [(m.ticker, m.reference_date) for m in manifest.mappings]
    if len(actual) != len(set(actual)) or set(actual) != expected_mappings or any(raw_dates.get(m.raw_id) != m.reference_date for m in manifest.mappings):
        fail('numerical_valid', 'INCOMPLETE_SIX_STOCK_FX_COVERAGE_PLAN')
    # A manifest cannot conceal a contemporaneously known competing provider,
    # orphan correction or new-ID overlapping observation. No averaging/fallback.
    for identity in sorted(heads):
        record = available[identity]
        if record.kind != 'raw':
            continue
        try:
            body = decode(record)
            if body.get('reference_date') in {d.isoformat() for d in manifest.expected_dates} and identity not in manifest.raw_ids:
                fail('history_valid', 'UNRESOLVED_OVERLAPPING_FX_OBSERVATION:' + identity)
        except (ValueError, KeyError, TypeError):
            fail('history_valid', 'UNREADABLE_KNOWN_FX_OBSERVATION:' + identity)
    for identity in manifest.raw_ids:
        if identity not in heads:
            fail('history_valid', 'SUPERSEDED_OR_UNAVAILABLE_RAW:' + identity)
    return FXEvaluation(status='ELIGIBLE_FOR_SYNTHETIC_REVIEW' if all(flags.values()) else 'HELD',
        request=request, snapshot=snapshot, engine_sha256=engine_hash(), reasons=tuple(sorted(reasons)),
        rates=tuple(rates), **flags)


def evaluate_fx(archive, request):
    snapshot = archive.snapshot()
    result = evaluate_snapshot(snapshot, request)
    archive.save_evaluation(result)  # CAS inside the same local audit/result transaction.
    return result


def replay_fx(evaluation, *, expected_hash):
    evaluation = FXEvaluation.model_validate(evaluation.model_dump(mode='json'))
    if input_hash(evaluation) != expected_hash or evaluation.engine_sha256 != engine_hash():
        raise ValueError('FX_REPLAY_INTEGRITY_OR_ENVIRONMENT_CHANGED')
    if evaluate_snapshot(evaluation.snapshot, evaluation.request) != evaluation:
        raise ValueError('FX_REPLAY_DIFFERS')
    return evaluation
