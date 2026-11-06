"""Strict 1C entry point; delegates signals and atomic persistence to Sprint 1B."""

from datetime import datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime

from models.daily_signals import DAILY_UNIVERSE, DailySignalInputs, DailySignalReport, ObservedTicker
from providers.daily_ohlcv_provider import DailyOHLCVProvider
from tools.daily_signal_pipeline import DailySignalStore, freeze_daily_inputs, replay_daily_signals
from tools.historical_snapshot import FrozenModel, canonical_json, input_hash
from tools.market_verification import (
    CalendarArtifact, CandleVerification, ProviderEvidenceArtifact, Scope,
    TrustRegistry, VerificationPolicy, verify_candle_finality,
)


def verification_source_sha256() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = sha256()
    for name in ('tools/market_verification.py', 'tools/verified_daily_pipeline.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    # New York civil-time interpretation also depends on the installed tzdb.
    digest.update(b'tzdata\0' + version('tzdata').encode())
    return digest.hexdigest()


class VerifiedDailyInputs(FrozenModel):
    schema_version: Literal[1]
    scope: Scope
    daily_inputs: DailySignalInputs
    calendar: CalendarArtifact
    evidence: ProviderEvidenceArtifact
    policy: VerificationPolicy
    verified_at: AwareDatetime
    trust_registry_sha256: str
    verification_source_sha256: str
    records: tuple[CandleVerification, ...]


class VerifiedDailyReport(FrozenModel):
    schema_version: Literal[1]
    scope: Scope
    verified_inputs_sha256: str
    calendar_sha256: str
    evidence_sha256: str
    trust_registry_sha256: str
    policy: VerificationPolicy
    records: tuple[CandleVerification, ...]
    daily_report: DailySignalReport
    disclosures: tuple[str, ...]


def freeze_verified_daily_inputs(
    calendar: CalendarArtifact, observed: tuple[ObservedTicker, ...], evidence: ProviderEvidenceArtifact, *,
    policy: VerificationPolicy, verified_at: datetime, decision_at: datetime,
    trust: TrustRegistry = TrustRegistry(),
) -> VerifiedDailyInputs:
    calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='json'))
    trust.require(calendar, 'calendar')
    trust.require(evidence, 'provider_evidence')
    daily = freeze_daily_inputs(calendar.as_daily_schedule(), observed, decision_at=decision_at)
    records = verify_candle_finality(daily, calendar, evidence, policy=policy, verified_at=verified_at, trust=trust)
    return VerifiedDailyInputs(
        schema_version=1, scope=trust.mode, daily_inputs=daily, calendar=calendar, evidence=evidence,
        policy=policy, verified_at=records[0].verified_at, trust_registry_sha256=input_hash(trust),
        verification_source_sha256=verification_source_sha256(), records=records,
    )


def replay_verified_daily_signals(
    inputs: VerifiedDailyInputs, *, expected_sha256: str, trust: TrustRegistry = TrustRegistry(),
) -> VerifiedDailyReport:
    inputs = VerifiedDailyInputs.model_validate(inputs.model_dump(mode='json'))
    if input_hash(inputs) != expected_sha256:
        raise ValueError('Verified daily input hash mismatch')
    if inputs.scope != trust.mode or inputs.trust_registry_sha256 != input_hash(trust):
        raise ValueError('External trust registry differs from the recorded verification root')
    if inputs.verification_source_sha256 != verification_source_sha256():
        raise ValueError('Verification source/timezone database mismatch')
    records = verify_candle_finality(
        inputs.daily_inputs, inputs.calendar, inputs.evidence, policy=inputs.policy,
        verified_at=inputs.verified_at, trust=trust,
    )
    if records != inputs.records:
        raise ValueError('Stored verification records differ from regenerated evidence checks')
    report = replay_daily_signals(inputs.daily_inputs, expected_sha256=input_hash(inputs.daily_inputs))
    return VerifiedDailyReport(
        schema_version=1, scope=inputs.scope, verified_inputs_sha256=expected_sha256,
        calendar_sha256=input_hash(inputs.calendar), evidence_sha256=input_hash(inputs.evidence),
        trust_registry_sha256=input_hash(trust), policy=inputs.policy, records=records, daily_report=report,
        disclosures=(
            'Synthetic-test scope is never real exchange/provider authority.' if trust.mode == 'synthetic_test'
            else 'Authority is an externally reviewed pinned artifact, not inferred from its label or hash.',
            'No official schedule or provider evidence is bundled; the default real-world trust registry is empty.',
            'Publication delay and official close are necessary but do not establish provider finality.',
            'USD research signals only; no FX, broker orders or execution.',
        ),
    )


def publish_verified_daily_signals(
    store: DailySignalStore, run_id: str, inputs: VerifiedDailyInputs, *,
    expected_sha256: str, trust: TrustRegistry = TrustRegistry(),
) -> VerifiedDailyReport:
    report = replay_verified_daily_signals(inputs, expected_sha256=expected_sha256, trust=trust)
    store.publish(run_id, inputs.daily_inputs, verification=inputs)
    return report


def load_verified_daily_signals(
    store: DailySignalStore, run_id: str, *, expected_sha256: str,
    trust: TrustRegistry = TrustRegistry(),
) -> VerifiedDailyReport:
    digest, content = store.load_verification(run_id)
    if digest != expected_sha256:
        raise ValueError('Stored verified input hash mismatch')
    inputs = VerifiedDailyInputs.model_validate_json(content)
    # Verify authority before asking the legacy loader to regenerate any decisions.
    report = replay_verified_daily_signals(inputs, expected_sha256=expected_sha256, trust=trust)
    _, stored = store.load(run_id, expected_sha256=input_hash(inputs.daily_inputs))
    if canonical_json(stored) != canonical_json(report.daily_report):
        raise ValueError('Verified report differs from the persisted daily result')
    return report


def ingest_verified_daily_signals(
    provider: DailyOHLCVProvider, calendar: CalendarArtifact, evidence: ProviderEvidenceArtifact, *,
    policy: VerificationPolicy, verified_at: datetime, decision_at: datetime,
    store: DailySignalStore, run_id: str, trust: TrustRegistry = TrustRegistry(),
) -> VerifiedDailyReport:
    """Explicit observation ingestion; no publication unless every proof passes."""
    calendar = CalendarArtifact.model_validate(calendar.model_dump(mode='json'))
    trust.require(calendar, 'calendar')
    trust.require(evidence, 'provider_evidence')
    schedule = calendar.as_daily_schedule()
    sessions = schedule.completed_sessions(decision_at)
    observed = []
    for ticker in DAILY_UNIVERSE:
        try:
            fetched = provider.fetch_daily(ticker, sessions)
            if fetched.snapshot.ticker != ticker:
                raise ValueError('Provider ticker mismatch')
            observed.append(fetched)
        except Exception as exc:
            raise RuntimeError(f'Verified daily provider failed for {ticker}') from exc
    inputs = freeze_verified_daily_inputs(
        calendar, tuple(observed), evidence, policy=policy, verified_at=verified_at,
        decision_at=decision_at, trust=trust,
    )
    return publish_verified_daily_signals(store, run_id, inputs, expected_sha256=input_hash(inputs), trust=trust)
