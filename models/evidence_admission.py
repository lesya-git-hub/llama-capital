"""Synthetic-only coordination contracts; none represents production trust."""
import base64
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from providers.provisional_market_data import ProvisionalBatch
from models.calendar_finality_evidence import EligibilityResult, SourceReceipt
from tools.historical_snapshot import FrozenModel


class CoordinationModel(FrozenModel):
    @field_validator('*', mode='after')
    @classmethod
    def canonical(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Nonblank coordination identity required')
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        return value


class Principal(CoordinationModel):
    principal_id: str
    roles: tuple[Literal['preparer', 'reviewer', 'admitter', 'revoker', 'source_operator', 'recovery', 'reader'], ...]


class SourceVersion(CoordinationModel):
    source_id: str
    instance_id: str
    generation: str
    scope: Literal['synthetic_test'] = 'synthetic_test'


class EvidenceObject(CoordinationModel):
    object_id: str
    version: str
    kind: Literal['raw_observation', 'source_receipt', 'license', 'clock', 'policy', 'environment', 'fx_placeholder']
    scope: Literal['synthetic_test', 'real'] = 'synthetic_test'
    body_b64: str
    dependencies: tuple[str, ...] = ()
    source_receipt: SourceReceipt | None = None

    def body(self):
        value = base64.b64decode(self.body_b64, validate=True)
        if len(value) > 8 * 1024 * 1024:
            raise ValueError('Evidence object byte budget exceeded')
        return value

    def fingerprint(self):
        # Renaming an object cannot bypass a typed-content revocation.
        return self.kind + ':' + self.scope + ':' + sha256(self.body()).hexdigest()

    @model_validator(mode='after')
    def valid(self):
        self.body()
        if len(set(self.dependencies)) != len(self.dependencies) or self.object_id in self.dependencies:
            raise ValueError('Invalid dependency references')
        return self


class ObservationBinding(CoordinationModel):
    ticker: str
    observation_id: str
    object_id: str


class AdmissionBundle(CoordinationModel):
    schema_version: Literal[1] = 1
    bundle_id: str
    version: str
    scope: Literal['synthetic_test', 'real'] = 'synthetic_test'
    purpose: Literal['USD_RESEARCH_SIGNALS'] = 'USD_RESEARCH_SIGNALS'
    fx_status: Literal['FX_NOT_INCLUDED'] = 'FX_NOT_INCLUDED'
    prepared_by: str
    sources: tuple[SourceVersion, ...]
    batch: ProvisionalBatch
    evaluation: EligibilityResult
    objects: tuple[EvidenceObject, ...]
    observations: tuple[ObservationBinding, ...]


class ReviewRequest(CoordinationModel):
    review_id: str
    bundle_id: str
    bundle_sha256: str
    epoch: int = Field(ge=1, strict=True)
    approved: bool = Field(strict=True)
    expires_at: AwareDatetime
    reason: str


class Checkpoint(CoordinationModel):
    authority_id: str
    sequence: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    epoch: int = Field(ge=1, strict=True)


class CommitReceipt(CoordinationModel):
    inspection_only: Literal[True] = True
    authority_id: str
    operation_id: str
    event_action: str
    sequence: int
    sha256: str


class BundleState(CoordinationModel):
    bundle_id: str
    state: Literal['PROVISIONAL', 'REVIEWED', 'ADMITTED', 'REVOKED', 'QUARANTINED']
    scope: Literal['synthetic_test'] = 'synthetic_test'
