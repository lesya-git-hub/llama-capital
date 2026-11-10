"""Offline six-stock quality checks. No credentials, network, persistence or admission."""
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
import math
from typing import Literal

from models.daily_signals import DAILY_UNIVERSE
from providers.alpaca_market_data import AlpacaDailyBatch
from tools.historical_snapshot import FrozenModel, input_hash
from tools.market_verification import CalendarArtifact, NEW_YORK


class QualityIssue(FrozenModel):
    code: str
    symbol: str | None = None
    session_date: str | None = None


class SymbolQuality(FrozenModel):
    symbol: str
    count: int
    expected_dates: tuple[str, ...]
    observed_dates: tuple[str, ...]
    missing_dates: tuple[str, ...]
    extra_dates: tuple[str, ...]
    duplicate_dates: tuple[str, ...]


class AlpacaQualityReport(FrozenModel):
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    scope: Literal['unverified'] = 'unverified'
    quality_outcome: Literal['CHECKS_PASSED', 'HELD']
    issues: tuple[QualityIssue, ...]
    symbols: tuple[SymbolQuality, ...]
    input_sha256: str | None
    calendar_sha256: str | None
    calendar_scope: Literal['real', 'synthetic_test'] | None
    calendar_assessment: Literal['SUPPLIED_FROZEN_CALENDAR_ONLY'] = 'SUPPLIED_FROZEN_CALENDAR_ONLY'
    feed_coverage: Literal['PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'] = 'PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'
    requested_adjustment: Literal['split'] = 'split'
    adjustment_assessment: Literal['PROVIDER_CLAIM_NOT_INDEPENDENTLY_VERIFIED'] = 'PROVIDER_CLAIM_NOT_INDEPENDENTLY_VERIFIED'
    corporate_action_evidence: Literal['NOT_ESTABLISHED'] = 'NOT_ESTABLISHED'
    candle_finality: Literal['NOT_ESTABLISHED'] = 'NOT_ESTABLISHED'
    rights_clearance: Literal['UNRESOLVED'] = 'UNRESOLVED'
    trust_admitted: Literal[False] = False
    history_batches_compared: int


class AlpacaQualityRejected(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('ALPACA_QUALITY_HELD')


def _snapshot(batch):
    if not isinstance(batch, AlpacaDailyBatch):
        raise ValueError('Expected Alpaca daily batch')
    # Revalidate nested copies without numeric/string serialization coercion.
    return AlpacaDailyBatch.model_validate(batch.model_dump(mode='python', warnings=False))


def _bar_identity(batch, symbol, bar):
    req = batch.request
    return (batch.provider, batch.source_endpoint, req.timeframe, req.feed,
        req.currency, req.adjustment, symbol, bar.timestamp.astimezone(NEW_YORK).date())


def _bar_content(bar):
    return (bar.timestamp.astimezone(timezone.utc), bar.session_date, bar.open, bar.high,
        bar.low, bar.close, bar.volume, bar.trade_count, bar.vwap)


def assess_alpaca_batch(batch, calendar=None, *, previous_batches=()):
    """Return inspection-only PASS/HELD evidence; never return a promoted batch."""
    issues, symbol_reports = set(), []
    snapshot, digest, calendar_digest, calendar_scope = None, None, None, None
    def issue(code, symbol=None, day=None):
        issues.add((code, symbol or '', day.isoformat() if day is not None else ''))
    try:
        snapshot = _snapshot(batch)
        digest = input_hash(snapshot)
    except Exception:
        issue('INVALID_BATCH_SCHEMA')

    frozen_calendar, schedule = None, None
    if calendar is None:
        issue('MISSING_FROZEN_CALENDAR')
    else:
        try:
            if not isinstance(calendar, CalendarArtifact):
                raise ValueError()
            if (calendar.coverage_end - calendar.coverage_start).days > 3661:
                raise ValueError()
            frozen_calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='python', warnings=False))
            schedule = frozen_calendar.as_daily_schedule()  # Reuse explicit coverage/divergence checks.
            calendar_digest, calendar_scope = input_hash(frozen_calendar), frozen_calendar.scope
        except Exception:
            issue('INVALID_OR_DIVERGENT_CALENDAR')

    previous = []
    try:
        if not isinstance(previous_batches, (tuple, list)) or len(previous_batches) > 64:
            raise ValueError()
        for prior in previous_batches:
            previous.append(_snapshot(prior))
    except Exception:
        issue('INVALID_REVISION_HISTORY')

    if snapshot is not None:
        req = snapshot.request
        if (len(req.symbols) != 6 or set(req.symbols) != set(DAILY_UNIVERSE)):
            issue('EXACT_SIX_STOCK_REQUEST_REQUIRED')
        actual_symbols = tuple(o.symbol for o in snapshot.observations)
        if len(actual_symbols) != 6 or set(actual_symbols) != set(DAILY_UNIVERSE):
            issue('MISSING_EXTRA_OR_DUPLICATE_SYMBOLS')
        if snapshot.acquired_start > snapshot.acquired_end or req.end > snapshot.acquired_start:
            issue('INVALID_ACQUISITION_CHRONOLOGY')
        if sum(len(o.bars) for o in snapshot.observations) > req.limit:
            issue('REQUEST_LIMIT_EXCEEDED')

        expected, sessions = None, {}
        if schedule is not None:
            first_day, last_day = req.start.astimezone(NEW_YORK).date(), req.end.astimezone(NEW_YORK).date()
            if not frozen_calendar.coverage_start <= first_day <= last_day < frozen_calendar.coverage_end:
                issue('CALENDAR_DOES_NOT_COVER_REQUEST')
            if frozen_calendar.available_at > snapshot.acquired_start:
                issue('CALENDAR_UNAVAILABLE_AT_ACQUISITION')
            sessions = {s.date: s for s in schedule.sessions if first_day <= s.date <= last_day}
            expected = tuple(sessions)
            if not expected:
                issue('NO_EXPECTED_TRADING_SESSIONS')
            for session in sessions.values():
                label = datetime.combine(session.date, time(), NEW_YORK).astimezone(timezone.utc)
                if not req.start <= label <= session.closes_at <= req.end:
                    issue('PARTIAL_SESSION_REQUEST', day=session.date)
                if session.closes_at > snapshot.acquired_start:
                    issue('SESSION_NOT_COMPLETED_AT_ACQUISITION', day=session.date)
            if req.expected_session_dates is not None and req.expected_session_dates != expected:
                issue('CALLER_EXPECTATIONS_CONFLICT_WITH_CALENDAR')

        # Compare actual overlapping contents, not retrieval times or window IDs.
        history = {}
        for prior in previous:
            if prior.acquired_end > snapshot.acquired_start:
                issue('REVISION_HISTORY_NOT_PRIOR')
            for observation in prior.observations:
                for bar in observation.bars:
                    key = _bar_identity(prior, observation.symbol, bar)
                    history.setdefault(key, set()).add(_bar_content(bar))

        for observation in snapshot.observations:
            symbol, observed = observation.symbol, []
            stamps = []
            for bar in observation.bars:
                instant = bar.timestamp.astimezone(timezone.utc)
                local, day = instant.astimezone(NEW_YORK), instant.astimezone(NEW_YORK).date()
                observed.append(day)
                stamps.append(instant)
                if bar.timestamp.utcoffset() != timezone.utc.utcoffset(None) or local.timetz().replace(tzinfo=None) != time():
                    issue('INVALID_UTC_DAILY_LABEL', symbol, day)
                if bar.session_date != day:
                    issue('SESSION_DATE_LABEL_MISMATCH', symbol, day)
                if not req.start <= instant <= req.end:
                    issue('BAR_OUTSIDE_REQUEST', symbol, day)
                if not math.isfinite(bar.volume) or not bar.volume.is_integer() or not 0 <= bar.volume <= 2**53 - 1:
                    issue('NONINTEGER_OR_UNSAFE_VOLUME', symbol, day)
                if bar.trade_count is not None:
                    if bar.volume > 0 and bar.trade_count == 0 or bar.volume == 0 and bar.trade_count > 0:
                        issue('TRADE_COUNT_VOLUME_INCONSISTENCY', symbol, day)
                if bar.vwap is not None:
                    if bar.volume == 0 or not bar.low <= bar.vwap <= bar.high:
                        issue('VWAP_VOLUME_OR_PRICE_INCONSISTENCY', symbol, day)
                prior_values = history.get(_bar_identity(snapshot, symbol, bar), set())
                if any(value != _bar_content(bar) for value in prior_values):
                    issue('UNVERIFIED_REVISION_CONFLICT', symbol, day)
            duplicates = {d for d in observed if observed.count(d) > 1}
            if duplicates:
                issue('DUPLICATE_SESSIONS', symbol)
            if any(b <= a for a, b in zip(stamps, stamps[1:])) or observed != sorted(observed):
                issue('NONCHRONOLOGICAL_SESSIONS', symbol)
            if expected is not None:
                missing, extra = set(expected) - set(observed), set(observed) - set(expected)
                if missing:
                    issue('MISSING_SESSIONS', symbol)
                if extra:
                    issue('EXTRA_OR_CLOSED_SESSIONS', symbol)
                symbol_reports.append(SymbolQuality(symbol=symbol, count=len(observed),
                    expected_dates=tuple(d.isoformat() for d in expected),
                    observed_dates=tuple(d.isoformat() for d in observed),
                    missing_dates=tuple(d.isoformat() for d in sorted(missing)),
                    extra_dates=tuple(d.isoformat() for d in sorted(extra)),
                    duplicate_dates=tuple(d.isoformat() for d in sorted(duplicates))))

    return AlpacaQualityReport(quality_outcome='HELD' if issues else 'CHECKS_PASSED',
        issues=tuple(QualityIssue(code=c, symbol=s or None, session_date=d or None) for c, s, d in sorted(issues)),
        symbols=tuple(symbol_reports), input_sha256=digest, calendar_sha256=calendar_digest,
        calendar_scope=calendar_scope, history_batches_compared=len(previous))


def validate_alpaca_batch(batch, calendar=None, *, previous_batches=()):
    """Reject any incomplete/invalid/conflicting batch; output remains PROVISIONAL."""
    report = assess_alpaca_batch(batch, calendar, previous_batches=previous_batches)
    if report.quality_outcome != 'CHECKS_PASSED':
        raise AlpacaQualityRejected(report)
    return report


@dataclass(frozen=True)
class QualityObservation:
    batch: AlpacaDailyBatch | None = field(default=None, repr=False)
    report: AlpacaQualityReport | None = None


class AlpacaValidationSession:
    """Bounded, append-only in-memory attempts. No conflict resolution or persistence."""
    def __init__(self, *, max_observations=64):
        if type(max_observations) is not int or not 1 <= max_observations <= 64:
            raise ValueError('Session capacity must be 1..64')
        self._records, self._capacity = (), max_observations

    @property
    def history(self):
        return self._records

    def validate(self, batch, calendar=None):
        if len(self._records) >= self._capacity:
            raise ValueError('ALPACA_QUALITY_HISTORY_CAPACITY')
        snapshot = None
        try:
            snapshot = _snapshot(batch)
        except Exception:
            pass
        priors = tuple(r.batch for r in self._records)
        report = assess_alpaca_batch(batch, calendar, previous_batches=priors)
        self._records += (QualityObservation(snapshot, report),)
        if report.quality_outcome != 'CHECKS_PASSED':
            raise AlpacaQualityRejected(report)
        return report
