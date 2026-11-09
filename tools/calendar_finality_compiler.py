"""Pure synthetic evidence compilation; never downloads, pins or publishes."""
from datetime import timedelta
import json

from models.calendar_finality_evidence import CalendarSnapshot, ExceptionalNotice, NoticeCoverage, ClaimDocument
from tools.historical_snapshot import input_hash
from tools.market_verification import NEW_YORK, ProviderEvidenceArtifact
from tools.calendar_finality_store import record_hash


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate evidence JSON key')
        value[key] = item
    return value


def document(record, model):
    def bad(value):
        raise ValueError('Nonfinite evidence JSON')
    return model.model_validate(json.loads(record.body.decode('utf-8'), object_pairs_hook=_unique, parse_constant=bad))


def active_records(records, kind):
    heads = {}
    for record in records.values():
        r = record.receipt
        if r.kind == kind:
            heads[(r.scope, r.source, r.logical_key)] = record
    return tuple(heads.values())


def resolve(records, ref, kind, *, at):
    record = records.get(ref.receipt_id)
    if record is None or record_hash(record) != ref.sha256 or record.receipt.kind != kind:
        raise ValueError('Missing/mismatched source evidence reference')
    r = record.receipt
    if r.scope != 'synthetic_test':
        raise ValueError('Real evidence remains PROVISIONAL in Stage A')
    if r.published_at is None or r.acquired_end + timedelta(milliseconds=r.uncertainty_ms) > at:
        raise ValueError('Missing publication time or unavailable/uncertain receipt')
    if not any(x.receipt.receipt_id == r.receipt_id for x in active_records(records, kind)):
        raise ValueError('Superseded source evidence; explicit new candidate required')
    return record


def compile_calendar(records, manifest, *, at):
    source = resolve(records, manifest.calendar, 'calendar', at=at)
    snapshot = document(source, CalendarSnapshot)
    calendar = snapshot.calendar
    if (calendar.scope != 'synthetic_test' or calendar.source != source.receipt.source
            or calendar.version != source.receipt.version or not snapshot.listing_history_confirmed
            or source.receipt.acquired_end > calendar.available_at):
        raise ValueError('Calendar identity/listing/availability evidence conflict')
    calendar.as_daily_schedule().completed_sessions(at)
    def calendar_view(value):
        view = {(r.exchange, r.date): ('open', r.opens_at, r.closes_at) for r in value.sessions}
        view.update({(r.exchange, r.date): ('closed', r.reason) for r in value.closed_dates})
        return view
    selected_view = calendar_view(calendar)
    for other in active_records(records, 'calendar'):
        if other.receipt.receipt_id == source.receipt.receipt_id:
            continue
        alternative = document(other, CalendarSnapshot).calendar
        if max(calendar.coverage_start, alternative.coverage_start) >= min(calendar.coverage_end, alternative.coverage_end):
            continue
        other_view = calendar_view(alternative)
        if (calendar.listings != alternative.listings or
                any(selected_view[k] != other_view[k] for k in selected_view.keys() & other_view.keys())):
            raise ValueError('Conflicting overlapping calendar snapshots; explicit resolution required')
    needs = {}
    for row in calendar.closed_dates:
        if row.reason == 'exceptional_closure':
            needs[(row.exchange, row.date.isoformat())] = ('exceptional_closure', None)
    for row in calendar.sessions:
        local = row.closes_at.astimezone(NEW_YORK).strftime('%H:%M')
        if local > snapshot.regular_close_local:
            raise ValueError('Unsupported extended session')
        if local < snapshot.regular_close_local:
            needs[(row.exchange, row.date.isoformat())] = ('early_close', row.closes_at)
    supplied = {}
    for ref in manifest.notices:
        notice_record = resolve(records, ref, 'notice', at=calendar.available_at)
        notice = document(notice_record, ExceptionalNotice)
        key = (notice.exchange, notice.session_date)
        if key in supplied or needs.get(key) != (notice.action, notice.closes_at):
            raise ValueError('Conflicting/unsupported exceptional notice')
        supplied[key] = notice_record.receipt.receipt_id
    if supplied.keys() != needs.keys():
        raise ValueError('Missing exceptional-closure/early-close confirmation')
    # An omitted competing notice is not resolved by leaving it out of a manifest.
    relevant = set()
    for record in active_records(records, 'notice'):
        notice = document(record, ExceptionalNotice)
        if (calendar.coverage_start.isoformat() <= notice.session_date < calendar.coverage_end.isoformat()
                and notice.exchange in {p.exchange for p in calendar.listings}):
            relevant.add(record.receipt.receipt_id)
    if relevant != set(supplied.values()):
        raise ValueError('Unresolved omitted/competing notice evidence')
    coverage_record = resolve(records, manifest.coverage, 'coverage', at=at)
    coverage = document(coverage_record, NoticeCoverage)
    if (not coverage.complete or coverage.calendar_sha256 != input_hash(calendar)
            or coverage.through < at or coverage.through > coverage_record.receipt.acquired_end):
        raise ValueError('Notice channel coverage is incomplete or stale')
    return calendar


def compile_provider_evidence(records, manifest, batch, *, at):
    if batch.calendar.scope != 'synthetic_test' or any(o.metadata.fixture_kind != 'synthetic_test' for o in batch.observations):
        raise ValueError('Real observations remain PROVISIONAL; synthetic compiler only')
    observations = {o.metadata.observation_id: o for o in batch.observations}
    expected = {(o.metadata.ticker, b.date): (o, b) for o in batch.observations for b in o.snapshot.bars}
    proofs, seen = [], set()
    provider = {o.metadata.provider_id for o in batch.observations}
    if len(provider) != 1:
        raise ValueError('Mixed providers')
    provider = next(iter(provider))
    selected = set()
    for ref in manifest.provider_claims:
        record = resolve(records, ref, 'provider_claim', at=at)
        selected.add(record.receipt.receipt_id)
        if record.receipt.source != provider:
            raise ValueError('Provider claim source mismatch')
        claims = document(record, ClaimDocument)
        for claim in claims.claims:
            proof = claim.proof
            pair = (proof.ticker, proof.date)
            observation = observations.get(claim.observation_id)
            if pair in seen or pair not in expected or observation is None:
                raise ValueError('Duplicate/missing/foreign candle claim')
            expected_observation, bar = expected[pair]
            if (observation != expected_observation or claim.observation_sha256 != observation.observation_sha256
                    or claim.raw_sha256 != observation.metadata.raw_sha256
                    or claim.normalizer_sha256 != observation.normalizer_sha256
                    or claim.dataset_id != observation.metadata.dataset_id
                    or claim.dataset_version != observation.metadata.dataset_version
                    or claim.feed != observation.metadata.feed or proof.candle_sha256 != input_hash(bar)):
                raise ValueError('Provider release/raw/normalization mapping mismatch')
            session = next(s for s in batch.calendar.sessions if s.exchange == observation.metadata.exchange and s.date == proof.date)
            if (proof.exchange != observation.metadata.exchange or proof.official_close != session.closes_at
                    or not proof.provider_final or not proof.completed_session
                    or not session.closes_at <= proof.issued_at <= record.receipt.published_at
                    or record.receipt.acquired_end + timedelta(milliseconds=record.receipt.uncertainty_ms) > observation.metadata.acquired_end):
                raise ValueError('Insufficient completion/session/receipt chronology evidence')
            seen.add(pair)
            proofs.append(proof)
    if seen != expected.keys():
        raise ValueError('Incomplete all-six/warm-up candle completion evidence')
    relevant = {r.receipt.receipt_id for r in active_records(records, 'provider_claim') if r.receipt.source == provider}
    if selected != relevant:
        raise ValueError('Unresolved omitted/competing provider release')
    return ProviderEvidenceArtifact(schema_version=1, scope='synthetic_test', source=provider,
        version='synthetic-evidence-projection-v1', available_at=at, candles=tuple(proofs))
