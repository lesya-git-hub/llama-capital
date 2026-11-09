"""Offline Stage A evidence. Approval records never grant production authority."""
from datetime import datetime, timezone
import json
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from tools.historical_snapshot import FrozenModel
from tools.market_verification import CalendarArtifact, CandleEvidence


class EvidenceModel(FrozenModel):
    @field_validator('*', mode='before')
    @classmethod
    def explicit_timestamp(cls, value, info):
        if info.field_name in {'published_at', 'acquired_start', 'acquired_end', 'closes_at',
                               'through', 'verified_at', 'decision_at', 'reviewed_at'}:
            if value is not None and not isinstance(value, (str, datetime)):
                raise ValueError('Explicit aware timestamp required')
        return value

    @field_validator('*', mode='after')
    @classmethod
    def canonical(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Nonblank evidence metadata required')
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        return value


class SourceReceipt(EvidenceModel):
    schema_version: Literal[1] = 1
    receipt_id: str = Field(min_length=1)
    kind: Literal['calendar', 'notice', 'coverage', 'provider_claim']
    scope: Literal['synthetic_test', 'real']
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    logical_key: str = Field(min_length=1)
    previous_id: str | None = None
    published_at: AwareDatetime | None
    acquired_start: AwareDatetime
    acquired_end: AwareDatetime
    clock_id: str = Field(min_length=1)
    uncertainty_ms: int = Field(ge=0, strict=True)
    provenance: str = Field(min_length=1)
    licensing_reference: str = Field(min_length=1)
    body_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'

    @field_validator('published_at', 'acquired_start', 'acquired_end', mode='before')
    @classmethod
    def explicit_time(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError('Explicit aware timestamps required')
        return value

    @model_validator(mode='after')
    def chronology(self):
        if (self.acquired_start > self.acquired_end or self.receipt_id == self.previous_id
                or self.published_at is not None and self.published_at > self.acquired_end):
            raise ValueError('Invalid source receipt chronology')
        return self


class EvidenceRef(EvidenceModel):
    receipt_id: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class CalendarSnapshot(EvidenceModel):
    schema_version: Literal[1] = 1
    calendar: CalendarArtifact
    regular_close_local: Literal['16:00'] = '16:00'  # Synthetic format only.
    listing_history_confirmed: StrictBool


class ExceptionalNotice(EvidenceModel):
    exchange: Literal['XNYS', 'XNAS']
    session_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    action: Literal['exceptional_closure', 'early_close']
    closes_at: AwareDatetime | None


class NoticeCoverage(EvidenceModel):
    calendar_sha256: str
    through: AwareDatetime
    complete: StrictBool


class ProviderClaim(EvidenceModel):
    observation_id: str
    observation_sha256: str
    raw_sha256: str
    normalizer_sha256: str
    dataset_id: str
    dataset_version: str
    feed: str
    release_id: str = Field(min_length=1)
    completion_policy_reference: str = Field(min_length=1)
    adjustment_policy_reference: str = Field(min_length=1)
    proof: CandleEvidence


class ClaimDocument(EvidenceModel):
    schema_version: Literal[1] = 1
    claims: tuple[ProviderClaim, ...]


class EvidenceManifest(EvidenceModel):
    schema_version: Literal[1] = 1
    manifest_id: str
    calendar: EvidenceRef
    notices: tuple[EvidenceRef, ...] = ()
    coverage: EvidenceRef
    provider_claims: tuple[EvidenceRef, ...] = ()


class EligibilityRequest(EvidenceModel):
    request_id: str
    scope: Literal['synthetic_test', 'real'] = 'synthetic_test'
    purpose: Literal['offline_synthetic_evaluation'] = 'offline_synthetic_evaluation'
    batch_id: str
    batch_sha256: str
    manifest_sha256: str
    verified_at: AwareDatetime
    decision_at: AwareDatetime
    publication_delay_seconds: int = Field(ge=0, strict=True)


class ReviewDisposition(EvidenceModel):
    review_id: str
    scope: Literal['synthetic_test', 'real'] = 'synthetic_test'
    request_sha256: str
    corpus_sha256: str
    operator_id: str
    authorization_id: str
    reason: str
    reviewed_at: AwareDatetime
    approved: StrictBool


class EligibilityResult(EvidenceModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test', 'real']
    status: Literal['PROVISIONAL', 'HELD_FOR_REVIEW', 'ELIGIBLE_FOR_1C_PROJECTION']
    request: EligibilityRequest
    manifest: EvidenceManifest
    review_sha256: str | None
    review_id: str | None
    corpus_sha256: str
    archive_corpus_sha256: str
    calendar_valid: StrictBool
    finality_valid: StrictBool
    reasons: tuple[str, ...]
    synthetic_projection_json: str | None
    engine_sha256: str

    @model_validator(mode='after')
    def isolation(self):
        if self.scope == 'real' and (self.status != 'PROVISIONAL' or self.synthetic_projection_json is not None
                or self.calendar_valid or self.finality_valid):
            raise ValueError('Real-world promotion is prohibited in Stage A')
        if self.status == 'ELIGIBLE_FOR_1C_PROJECTION':
            if not self.calendar_valid or not self.finality_valid or self.reasons or self.synthetic_projection_json is None:
                raise ValueError('Inconsistent synthetic eligibility')
            if json.loads(self.synthetic_projection_json).get('scope') != 'synthetic_test':
                raise ValueError('Only synthetic projection contents are permitted')
        elif self.synthetic_projection_json is not None:
            raise ValueError('Rejected/provisional result cannot contain a final projection')
        return self
