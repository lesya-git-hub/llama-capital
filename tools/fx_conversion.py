"""Offline Decimal FX valuation. No provider transport, accounting or execution."""

from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from tools.historical_snapshot import FrozenModel, input_hash
from tools.pretrade_risk import Holding, Mark, Outstanding, Proposal, ValuationSnapshot


FX_CONTEXT = Context(prec=80, rounding=ROUND_HALF_EVEN)
QUANTUM = Decimal('0.000000000001')
Amount = Annotated[Decimal, Field(ge=0, le=Decimal('1e12'), decimal_places=12)]
Rate = Annotated[Decimal, Field(gt=0, le=Decimal('1e12'), decimal_places=24, max_digits=36)]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class FXInput(FrozenModel):
    model_config = {**FrozenModel.model_config, 'validate_default': True}

    @field_validator('*', mode='before')
    @classmethod
    def reject_float_bool(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('Explicit Decimal, decimal string or integer required; no binary floats/booleans')
        return value

    @field_validator('*', mode='after')
    @classmethod
    def canonical(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Nonblank metadata required')
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, Decimal):
            with localcontext(FX_CONTEXT):
                return value.normalize() if value else Decimal(0)
        return value


class FXQuote(FXInput):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test', 'unverified']
    pair: Literal['USD_EUR']
    direction: Literal['EUR_PER_USD', 'USD_PER_EUR']
    rate: Rate
    effective_at: AwareDatetime
    retrieved_at: AwareDatetime
    provider_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    quote_id: str = Field(min_length=1)
    payload_sha256: Digest
    price_convention: Literal['indicative_mid']
    provenance: str = Field(min_length=1)

    @field_validator('effective_at', 'retrieved_at', mode='before')
    @classmethod
    def explicit_timestamp(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError('Explicit timezone-aware timestamp required')
        return value

    @model_validator(mode='after')
    def chronology(self):
        if self.effective_at > self.retrieved_at:
            raise ValueError('Quote effective time follows retrieval')
        return self


class FXQuoteBook(FXInput):
    quotes: tuple[FXQuote, ...]

    @model_validator(mode='after')
    def unique(self):
        # Identity is provider + dataset + quote ID. Even exact duplicates reject.
        keys = [(q.provider_id, q.dataset_id, q.quote_id) for q in self.quotes]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate or conflicting FX quote identity')
        object.__setattr__(self, 'quotes', tuple(sorted(self.quotes, key=lambda q: (q.provider_id, q.dataset_id, q.quote_id))))
        return self


class CanonicalFX(FXInput):
    direction: Literal['EUR_PER_USD'] = 'EUR_PER_USD'
    source_quote: FXQuote
    operation: Literal['direct', 'explicit_reciprocal']

    @model_validator(mode='after')
    def direction_matches(self):
        expected = 'EUR_PER_USD' if self.operation == 'direct' else 'USD_PER_EUR'
        if self.source_quote.direction != expected:
            raise ValueError('Explicit reciprocal operation required for reverse direction')
        return self

    @property
    def rate(self) -> Decimal:
        with localcontext(FX_CONTEXT):
            return self.source_quote.rate if self.operation == 'direct' else Decimal(1) / self.source_quote.rate


def canonical_quote(quote: FXQuote) -> CanonicalFX:
    quote = FXQuote.model_validate(quote.model_dump(mode='json'))
    return CanonicalFX(source_quote=quote, operation='direct')


def reciprocal_quote(quote: FXQuote) -> CanonicalFX:
    """Explicitly invert USD_PER_EUR without rewriting the provider's source rate."""
    quote = FXQuote.model_validate(quote.model_dump(mode='json'))
    return CanonicalFX(source_quote=quote, operation='explicit_reciprocal')


class FXPolicy(FXInput):
    version: str = 'fx-research-1'
    max_age_seconds: Annotated[int, Field(strict=True, ge=0)]
    approval: Literal['not_required', 'required'] = 'not_required'
    rounding: Literal['ROUND_HALF_EVEN_12DP'] = 'ROUND_HALF_EVEN_12DP'


class FXSourcePin(FXInput):
    provider_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    quote_sha256: Digest
    review_reference: str = Field(min_length=1)


class FXTrustRegistry(FXInput):
    """Separately supplied exact-content reviews; empty by default. Not a signature."""
    pins: tuple[FXSourcePin, ...] = ()


def validate_quote(fx: CanonicalFX, policy: FXPolicy, *, valuation_at: datetime,
                   trust: FXTrustRegistry = FXTrustRegistry()) -> CanonicalFX:
    fx = CanonicalFX.model_validate(fx.model_dump(mode='json'))
    policy = FXPolicy.model_validate(policy.model_dump(mode='json'))
    trust = FXTrustRegistry.model_validate(trust.model_dump(mode='json'))
    if not isinstance(valuation_at, datetime) or valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise ValueError('Explicit timezone-aware valuation timestamp required')
    quote = fx.source_quote
    if quote.retrieved_at > valuation_at or quote.effective_at > valuation_at:
        raise ValueError('Future or not-yet-retrieved FX quote')
    if (valuation_at - quote.effective_at).total_seconds() > policy.max_age_seconds:
        raise ValueError('Stale FX effective timestamp')
    if policy.approval == 'required' and not any(
        (p.provider_id, p.dataset_id, p.quote_sha256) == (quote.provider_id, quote.dataset_id, input_hash(quote))
        for p in trust.pins
    ):
        raise ValueError('Unapproved FX source: separately reviewed exact-content pin required')
    return fx


class ConversionRequest(FXInput):
    kind: Literal['USD_PRICE', 'USD_NOTIONAL', 'EUR_NOTIONAL', 'USD_EQUITY_VALUE', 'USD_COST']
    amount: Amount
    quantity: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)] = 1

    @model_validator(mode='after')
    def units(self):
        if self.kind != 'USD_EQUITY_VALUE' and self.quantity != 1:
            raise ValueError('Quantity applies only to multi-share equity valuation')
        if self.kind in ('USD_PRICE', 'USD_EQUITY_VALUE') and self.amount == 0:
            raise ValueError('Equity price must be positive')
        return self


class ConversionRecord(FrozenModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test', 'unverified']
    fx: CanonicalFX
    policy: FXPolicy
    request: ConversionRequest
    valuation_at: AwareDatetime
    currency: Literal['EUR', 'USD']
    value: Decimal
    quote_sha256: Digest
    request_sha256: Digest
    policy_sha256: Digest
    trust_sha256: Digest
    engine_sha256: Digest


def convert(request: ConversionRequest, fx: CanonicalFX, policy: FXPolicy, *, valuation_at: datetime,
            trust: FXTrustRegistry = FXTrustRegistry()) -> ConversionRecord:
    request = ConversionRequest.model_validate(request.model_dump(mode='json'))
    policy = FXPolicy.model_validate(policy.model_dump(mode='json'))
    trust = FXTrustRegistry.model_validate(trust.model_dump(mode='json'))
    fx = validate_quote(fx, policy, valuation_at=valuation_at, trust=trust)
    with localcontext(FX_CONTEXT):
        amount = request.amount * request.quantity
        # Divide by the original reciprocal rate directly: never round the
        # derived reciprocal and then multiply by it.
        multiply = (fx.operation == 'direct') != (request.kind == 'EUR_NOTIONAL')
        raw = amount * fx.source_quote.rate if multiply else amount / fx.source_quote.rate
        value = raw.quantize(QUANTUM).normalize() if raw else Decimal(0)
    return ConversionRecord(
        scope=fx.source_quote.scope, fx=fx, policy=policy, request=request,
        valuation_at=valuation_at.astimezone(timezone.utc),
        currency='USD' if request.kind == 'EUR_NOTIONAL' else 'EUR', value=value,
        quote_sha256=input_hash(fx.source_quote), request_sha256=input_hash(request),
        policy_sha256=input_hash(policy), trust_sha256=input_hash(trust),
        engine_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def replay_conversion(record: ConversionRecord, *, expected_sha256: str,
                      trust: FXTrustRegistry = FXTrustRegistry()) -> ConversionRecord:
    record = ConversionRecord.model_validate(record.model_dump(mode='json'))
    if input_hash(record) != expected_sha256:
        raise ValueError('FX conversion snapshot integrity mismatch')
    regenerated = convert(record.request, record.fx, record.policy, valuation_at=record.valuation_at, trust=trust)
    if regenerated != record:
        raise ValueError('FX replay differs from recorded output, source, policy or trust root')
    return regenerated


# Reuse 1E shapes while making the new USD boundary stricter about floats.
class USDMark(Mark, FXInput):
    pass


class USDHolding(Holding, FXInput):
    pass


class USDProposal(Proposal, FXInput):
    currency: Literal['USD'] = 'USD'


class USDOutstanding(FXInput):
    order: USDProposal
    status: Literal['CREATED', 'ACCEPTED']


class RiskConversionRequest(FXInput):
    scope: Literal['synthetic_test'] = 'synthetic_test'
    snapshot_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    as_of: AwareDatetime
    cash_eur: Amount  # Already EUR; never converted.
    holdings_usd: tuple[USDHolding, ...] = ()
    marks_usd: tuple[USDMark, ...]
    outstanding_usd: tuple[USDOutstanding, ...] = ()
    prior_proposal_ids: tuple[str, ...] = ()
    proposal_usd: USDProposal


class EURRiskInputs(FrozenModel):
    scope: Literal['synthetic_test'] = 'synthetic_test'
    request: RiskConversionRequest
    fx: CanonicalFX
    policy: FXPolicy
    valuation_at: AwareDatetime
    snapshot: ValuationSnapshot
    proposal: Proposal
    conversions: tuple[ConversionRecord, ...]
    request_sha256: Digest
    snapshot_sha256: Digest
    proposal_sha256: Digest
    fx_sha256: Digest


def convert_risk_inputs(request: RiskConversionRequest, fx: CanonicalFX, policy: FXPolicy, *,
                        valuation_at: datetime, trust: FXTrustRegistry = FXTrustRegistry()) -> EURRiskInputs:
    """Produce 1E-compatible synthetic EUR inputs, never a risk decision/order."""
    request = RiskConversionRequest.model_validate(request.model_dump(mode='json'))
    fx = validate_quote(fx, policy, valuation_at=valuation_at, trust=trust)
    if fx.source_quote.scope != 'synthetic_test':
        raise ValueError('Risk adapter requires synthetic FX fixtures, not unverified real data')
    policy = FXPolicy.model_validate(policy.model_dump(mode='json'))
    if request.as_of > valuation_at or any(m.as_of > request.as_of for m in request.marks_usd):
        raise ValueError('USD valuation timestamp violates causality')
    records = []
    def eur(value, kind='USD_COST'):
        record = convert(ConversionRequest(kind=kind, amount=value), fx, policy,
                         valuation_at=valuation_at, trust=trust)
        records.append(record)
        return record.value
    def proposal(value):
        data = value.model_dump(mode='python')
        for name in ('entry_price', 'stop_price'):
            data[name] = eur(data[name], 'USD_PRICE')
        for name in ('commission', 'slippage', 'exit_commission', 'exit_slippage'):
            data[name] = eur(data[name])
        data['currency'] = 'EUR'
        return Proposal.model_validate(data)
    holdings = []
    for h in sorted(request.holdings_usd, key=lambda h: h.ticker):
        holdings.append(Holding(ticker=h.ticker, quantity=h.quantity,
            stop_price=eur(h.stop_price, 'USD_PRICE'), exit_commission=eur(h.exit_commission),
            exit_slippage=eur(h.exit_slippage)))
    # Mark freshness must reflect both the equity mark and the FX effective time.
    marks = tuple(Mark(ticker=m.ticker, price=eur(m.price, 'USD_PRICE'),
                       as_of=min(m.as_of, fx.source_quote.effective_at))
                  for m in sorted(request.marks_usd, key=lambda m: m.ticker))
    pending = tuple(Outstanding(order=proposal(o.order), status=o.status)
                    for o in sorted(request.outstanding_usd, key=lambda o: o.order.proposal_id))
    result = proposal(request.proposal_usd)
    # Distinguish a converted snapshot from its USD source with an integrity ID.
    source_hash = input_hash(request)
    fx_hash = input_hash(fx)
    snapshot = ValuationSnapshot(
        snapshot_id=f'{request.snapshot_id}:fx:{source_hash}:{fx_hash}',
        source=f'{request.source}:synthetic-fx:{fx.source_quote.provider_id}',
        as_of=request.as_of, currency='EUR', cash=request.cash_eur, holdings=tuple(holdings),
        marks=marks, outstanding=pending, prior_proposal_ids=request.prior_proposal_ids,
    )
    return EURRiskInputs(request=request, fx=fx, policy=policy, valuation_at=valuation_at,
        snapshot=snapshot, proposal=result, conversions=tuple(records), request_sha256=source_hash,
        snapshot_sha256=input_hash(snapshot), proposal_sha256=input_hash(result), fx_sha256=fx_hash)


def replay_risk_inputs(record: EURRiskInputs, *, expected_sha256: str,
                       trust: FXTrustRegistry = FXTrustRegistry()) -> EURRiskInputs:
    record = EURRiskInputs.model_validate(record.model_dump(mode='json'))
    if input_hash(record) != expected_sha256:
        raise ValueError('FX risk-input snapshot integrity mismatch')
    regenerated = convert_risk_inputs(record.request, record.fx, record.policy,
                                      valuation_at=record.valuation_at, trust=trust)
    if regenerated != record:
        raise ValueError('FX risk-input replay mismatch')
    return regenerated
