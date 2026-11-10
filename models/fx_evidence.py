"""Isolated synthetic FX evidence. Eligibility never represents trust admission."""
import base64
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator
from tools.historical_snapshot import FrozenModel

class FXModel(FrozenModel):
    @field_validator('*', mode='before')
    @classmethod
    def explicit_values(cls, value, info):
        if isinstance(value, (float, bool)) and info.field_name not in (
                'complete', 'confirmed', 'publication_expected', 'inspection_only', 'numerical_valid',
                'publication_valid', 'calendar_valid', 'temporal_valid', 'history_valid'):
            raise ValueError('Explicit text/integer values required')
        if info.field_name in ('effective_at', 'published_at', 'acquired_start', 'acquired_end', 'decision_at', 'evidence_cutoff'):
            if value is not None and not isinstance(value, (str, datetime)):
                raise ValueError('Explicit aware timestamp required')
        if info.field_name in ('reference_date', 'date', 'coverage_start', 'coverage_end'):
            if not (type(value) is date or isinstance(value, str) and len(value) == 10):
                raise ValueError('Plain date required')
        return value

    @field_validator('*', mode='after')
    @classmethod
    def canonical(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Nonblank evidence value required')
        return value.astimezone(timezone.utc) if isinstance(value, datetime) else value


class FXReceipt(FXModel):
    observation_id: str
    version: str
    logical_key: str
    previous_id: str | None = None
    scope: Literal['synthetic_test'] = 'synthetic_test'
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    provider_id: str
    dataset_id: str
    feed: str
    source_instance: str
    source_generation: str
    release_id: str
    acquired_start: AwareDatetime
    acquired_end: AwareDatetime
    published_at: AwareDatetime | None
    clock_id: str
    uncertainty_ms: int = Field(ge=0, le=86400000, strict=True)
    provenance: str
    licensing_reference: str
    content_type: Literal['application/json'] = 'application/json'
    encoding: Literal['utf-8'] = 'utf-8'
    response_status: int = Field(ge=100, le=599, strict=True)
    page_count: int = Field(ge=1, strict=True)
    complete: StrictBool
    query_identity: str
    raw_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def chronology(self):
        if self.acquired_start > self.acquired_end or self.previous_id == self.observation_id:
            raise ValueError('Invalid receipt acquisition/lineage')
        # Missing/future publication is preserved for fail-closed evaluation.
        return self


class FXRecord(FXModel):
    kind: Literal['raw', 'series', 'calendar', 'publication', 'document']
    receipt: FXReceipt
    body_b64: str

    def body(self):
        value = base64.b64decode(self.body_b64, validate=True)
        if not value or len(value) > 1024 * 1024:
            raise ValueError('FX evidence byte budget exceeded')
        return value


class FXSeries(FXModel):
    provider_id: str
    dataset_id: str
    feed: str
    base: Literal['USD', 'EUR']
    quote: Literal['USD', 'EUR']
    direction: Literal['EUR_PER_USD', 'USD_PER_EUR']
    operation: Literal['direct', 'explicit_reciprocal']
    units: Literal['quote_per_one_base']
    rate_kind: Literal['official_reference']
    adjustment: Literal['NONE']
    methodology_version: str
    methodology_ref: str
    correction_policy_ref: str
    license_ref: str
    clock_ref: str
    calendar_id: str
    timezone: str
    source_precision: int = Field(ge=0, le=24, strict=True)
    source_rounding: str
    original_symbol: str


class FXCalendarDay(FXModel):
    date: date
    publication_expected: StrictBool
    exception_ref: str | None = None


class FXCalendar(FXModel):
    provider_id: str
    calendar_id: str
    timezone: str
    coverage_start: date
    coverage_end: date  # Inclusive, every civil date must be explicit.
    schedule_ref: str
    days: tuple[FXCalendarDay, ...]


class FXPublication(FXModel):
    raw_id: str
    raw_sha256: str
    raw_record_sha256: str
    release_id: str
    series_id: str
    confirmed: StrictBool
    complete: StrictBool
    claim: Literal['published_release_confirmed']
    publication_artifact_ref: str


class FXMapping(FXModel):
    ticker: str
    reference_date: date
    raw_id: str


class FXManifest(FXModel):
    manifest_id: str
    series_id: str
    raw_ids: tuple[str, ...]
    expected_dates: tuple[date, ...]
    mappings: tuple[FXMapping, ...]  # Pure coverage plan; no portfolio or orders.


class FXPolicy(FXModel):
    version: str
    purpose: Literal['offline_synthetic_reference_evaluation'] = 'offline_synthetic_reference_evaluation'
    historical_mode: Literal['AS_KNOWN_TO_THIS_SYSTEM'] = 'AS_KNOWN_TO_THIS_SYSTEM'
    carry: Literal['NO_CARRY'] = 'NO_CARRY'
    max_age_seconds: int = Field(ge=0, strict=True)
    rounding: Literal['ROUND_HALF_EVEN_12DP'] = 'ROUND_HALF_EVEN_12DP'


class FXSnapshot(FXModel):
    generation: str
    records: tuple[FXRecord, ...]


class FXEvaluationRequest(FXModel):
    evaluation_id: str
    manifest: FXManifest
    policy: FXPolicy
    decision_at: AwareDatetime
    evidence_cutoff: AwareDatetime
    expected_generation: str


class FXNormalizedRate(FXModel):
    raw_id: str
    raw_record_sha256: str
    series_sha256: str
    reference_date: date
    original_rate_text: str
    original_direction: Literal['EUR_PER_USD', 'USD_PER_EUR']
    operation: Literal['direct', 'explicit_reciprocal']
    canonical_direction: Literal['EUR_PER_USD'] = 'EUR_PER_USD'
    canonical_rate_text: str  # Precision-80 derived value, never an executable quote.
    effective_at: AwareDatetime
    published_at: AwareDatetime
    acquired_end: AwareDatetime
    rate_kind: Literal['official_reference'] = 'official_reference'
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'


class FXEvaluation(FXModel):
    scope: Literal['synthetic_test'] = 'synthetic_test'
    status: Literal['ELIGIBLE_FOR_SYNTHETIC_REVIEW', 'HELD']
    inspection_only: Literal[True] = True
    request: FXEvaluationRequest
    snapshot: FXSnapshot
    engine_sha256: str
    reasons: tuple[str, ...]
    numerical_valid: StrictBool
    publication_valid: StrictBool
    calendar_valid: StrictBool
    temporal_valid: StrictBool
    history_valid: StrictBool
    rates: tuple[FXNormalizedRate, ...]
