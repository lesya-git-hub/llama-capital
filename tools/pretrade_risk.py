"""Pure synthetic EUR pre-trade research decisions; no broker access or mutation."""

from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from tools.historical_snapshot import FrozenModel, input_hash


Amount = Annotated[Decimal, Field(ge=0, le=Decimal('1e12'), decimal_places=12)]
Price = Annotated[Decimal, Field(gt=0, le=Decimal('1e12'), decimal_places=12)]
Fraction = Annotated[Decimal, Field(gt=0, le=1, decimal_places=12)]
Shares = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]


class RiskModel(FrozenModel):
    model_config = {**FrozenModel.model_config, 'validate_default': True}

    @field_validator('*', mode='before')
    @classmethod
    def no_boolean_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError('Boolean values are not risk inputs')
        return value

    @field_validator('*', mode='after')
    @classmethod
    def canonical_values(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Nonblank identity required')
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, Decimal):
            # Canonical numeric identity independent of caller decimal context.
            with localcontext(Context(prec=50)):
                return value.normalize() if value else Decimal(0)
        return value


class RiskConfiguration(RiskModel):
    schema_version: Literal[1] = 1
    version: str = 'research-1'
    starting_capital: Price = Decimal('10000')
    max_position: Fraction = Decimal('.20')
    max_invested: Fraction = Decimal('.80')
    min_cash: Annotated[Decimal, Field(ge=0, le=1, decimal_places=12)] = Decimal('.20')
    max_position_risk: Fraction = Decimal('.01')
    max_aggregate_risk: Fraction = Decimal('.04')
    max_age_seconds: Annotated[int, Field(strict=True, ge=0)]  # Explicit valuation policy.
    currency: Literal['EUR'] = 'EUR'


class Mark(RiskModel):
    ticker: str = Field(pattern=r'^[A-Z][A-Z0-9.=-]*$')
    price: Price
    as_of: AwareDatetime


class Holding(RiskModel):
    ticker: str = Field(pattern=r'^[A-Z][A-Z0-9.=-]*$')
    quantity: Shares
    stop_price: Price
    exit_commission: Amount  # Explicit planned total fee, not an inferred rate.
    exit_slippage: Amount  # EUR per share, adverse at stop.


class Proposal(RiskModel):
    proposal_id: str = Field(min_length=1)
    ticker: str = Field(pattern=r'^[A-Z][A-Z0-9.=-]*$')
    side: Literal['BUY', 'SELL']
    quantity: Shares
    entry_price: Price  # Reference execution price for either side.
    stop_price: Price
    commission: Amount
    slippage: Amount  # Adverse EUR per share.
    exit_commission: Amount
    exit_slippage: Amount
    currency: str = Field(min_length=1)

    @model_validator(mode='after')
    def valid_prices(self):
        if (self.side == 'BUY' and self.stop_price >= self.entry_price) or self.exit_slippage >= self.stop_price:
            raise ValueError('BUY stop must be below reference price; positive adverse stop execution required')
        if self.side == 'SELL' and self.slippage >= self.entry_price:
            raise ValueError('SELL execution price must remain positive')
        return self


class Outstanding(RiskModel):
    order: Proposal
    status: Literal['CREATED', 'ACCEPTED']


class ValuationSnapshot(RiskModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test'] = 'synthetic_test'
    snapshot_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    as_of: AwareDatetime
    currency: str = Field(min_length=1)
    cash: Amount  # Unreserved ledger cash, not already net of pending orders.
    holdings: tuple[Holding, ...] = ()
    marks: tuple[Mark, ...]
    outstanding: tuple[Outstanding, ...] = ()
    prior_proposal_ids: tuple[str, ...] = ()  # Caller-maintained advisory history.

    @model_validator(mode='after')
    def unique(self):
        for values in ([h.ticker for h in self.holdings], [m.ticker for m in self.marks],
                       [p.order.proposal_id for p in self.outstanding], list(self.prior_proposal_ids)):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate snapshot identities')
        for name, key in (('holdings', lambda h: h.ticker), ('marks', lambda m: m.ticker),
                          ('outstanding', lambda p: p.order.proposal_id)):
            object.__setattr__(self, name, tuple(sorted(getattr(self, name), key=key)))
        object.__setattr__(self, 'prior_proposal_ids', tuple(sorted(self.prior_proposal_ids)))
        return self


class PositionMetrics(FrozenModel):
    ticker: str
    quantity: int
    value: Decimal
    concentration: Decimal | None
    planned_risk: Decimal


class RiskMetrics(FrozenModel):
    equity: Decimal
    limit_equity: Decimal
    cash: Decimal
    invested: Decimal
    invested_fraction: Decimal | None
    cash_fraction: Decimal | None
    planned_risk: Decimal
    risk_fraction: Decimal | None
    positions: tuple[PositionMetrics, ...]


class RiskDecision(FrozenModel):
    schema_version: Literal[1] = 1
    scope: Literal['synthetic_test'] = 'synthetic_test'
    evaluated_at: AwareDatetime
    snapshot_id: str
    proposal_id: str
    configuration_version: str
    snapshot_sha256: str
    proposal_sha256: str
    configuration_sha256: str
    engine_sha256: str
    decision: Literal['APPROVED', 'REJECTED']
    reasons: tuple[str, ...]
    current: RiskMetrics | None
    projected: RiskMetrics | None
    advisory: Literal[True] = True


def evaluate_pretrade(snapshot: ValuationSnapshot, proposal: Proposal, configuration: RiskConfiguration,
                      *, evaluated_at: datetime) -> RiskDecision:
    """Malformed structures raise ValueError; unsafe valid structures return REJECTED.

    BUY limits remain strict. Qualifying reducing SELLs may retain existing breaches.
    No approval is remembered internally and no cash/shares are reserved.
    """
    snapshot = ValuationSnapshot.model_validate(snapshot.model_dump(mode='json'))
    proposal = Proposal.model_validate(proposal.model_dump(mode='json'))
    configuration = RiskConfiguration.model_validate(configuration.model_dump(mode='json'))
    if not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError('Explicit timezone-aware evaluation time required')
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    with localcontext(Context(prec=50)):
        reasons, current, projected = _evaluate(snapshot, proposal, configuration, evaluated_at)
        exception_used = (proposal.side == 'SELL' and not reasons and projected is not None
            and bool(_exposure_risk_breaches(projected, configuration)))
    return RiskDecision(
        evaluated_at=evaluated_at, snapshot_id=snapshot.snapshot_id, proposal_id=proposal.proposal_id,
        configuration_version=configuration.version, snapshot_sha256=input_hash(snapshot),
        proposal_sha256=input_hash(proposal), configuration_sha256=input_hash(configuration),
        engine_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        decision='REJECTED' if reasons else 'APPROVED', reasons=tuple(reasons) or (
            ('RISK_REDUCING_SELL_EXCEPTION: pre-existing exposure/risk breaches retained',)
            if exception_used else ('WITHIN_LIMITS',)),
        current=current, projected=projected,
    )


def _exposure_risk_breaches(metrics, configuration):
    """Only these limits may qualify for a reducing SELL exception."""
    reasons = []
    base = metrics.limit_equity
    if metrics.invested > base * configuration.max_invested:
        reasons.append('TOTAL_EXPOSURE: maximum invested exposure exceeded')
    if metrics.planned_risk > base * configuration.max_aggregate_risk:
        reasons.append('AGGREGATE_RISK: aggregate planned stop-loss risk exceeded')
    for position in metrics.positions:
        if position.value > base * configuration.max_position:
            reasons.append(f'POSITION_EXPOSURE: {position.ticker} concentration exceeded')
        if position.planned_risk > base * configuration.max_position_risk:
            reasons.append(f'POSITION_RISK: {position.ticker} planned stop-loss risk exceeded')
    return reasons


def _evaluate(s, p, c, now):
    reasons = []
    pending = tuple(o.order for o in s.outstanding)
    if p.proposal_id in s.prior_proposal_ids or any(o.proposal_id == p.proposal_id for o in pending):
        reasons.append('DUPLICATE_PROPOSAL: proposal identity already recorded')
    if s.currency != 'EUR' or any(o.currency != 'EUR' for o in (*pending, p)):
        return reasons + ['CURRENCY_MISMATCH: explicit synthetic EUR inputs required; FX unavailable'], None, None
    marks = {m.ticker: m.price for m in s.marks}
    required = {h.ticker for h in s.holdings} | {o.ticker for o in (*pending, p)}
    if required - marks.keys():
        return reasons + ['MISSING_VALUATION: explicit mark required for every held or proposed ticker'], None, None
    if any(not 0 <= (now - stamp).total_seconds() <= c.max_age_seconds
           for stamp in (s.as_of, *(m.as_of for m in s.marks))):
        return reasons + ['STALE_VALUATION: snapshot/marks are stale or in the future'], None, None
    if any(m.as_of > s.as_of for m in s.marks):
        return reasons + ['VALUATION_CAUSALITY: mark is newer than portfolio snapshot'], None, None
    quantities = {h.ticker: h.quantity for h in s.holdings}
    risks, held_risk_per_share = {}, {}
    for h in s.holdings:
        if (p.side == 'BUY' and h.stop_price >= marks[h.ticker]) or h.exit_slippage >= h.stop_price:
            return reasons + ['INVALID_STOP: held-position stop must be below current mark'], None, None
        # SELL is an exit, not a new stop-protected entry. A breached stop cannot
        # supply negative risk or protective credit: conservatively reserve the
        # full marked value of any residual shares, plus existing exit costs.
        # BUY eligibility and all portfolio limit checks remain unchanged.
        distance = (marks[h.ticker] - h.stop_price if h.stop_price < marks[h.ticker]
                    else marks[h.ticker]) + h.exit_slippage
        held_risk_per_share[h.ticker] = distance
        risks[h.ticker] = h.quantity * distance + h.exit_commission
    def metrics(cash, quantities, risks, denominator=None):
        invested = sum((marks[t] * q for t, q in quantities.items()), Decimal(0))
        equity = cash + invested
        base = equity if denominator is None else min(equity, denominator)
        # Nonpositive equity is rejected separately; undefined ratios stay null.
        def ratio(value):
            return value / base if base > 0 else None
        total_risk = sum(risks.values(), Decimal(0))
        positions = tuple(PositionMetrics(ticker=t, quantity=q, value=marks[t] * q,
                         concentration=ratio(marks[t] * q), planned_risk=risks.get(t, Decimal(0)))
                         for t, q in sorted(quantities.items()) if q)
        return RiskMetrics(equity=equity, limit_equity=base, cash=cash, invested=invested,
                           invested_fraction=ratio(invested), cash_fraction=ratio(cash),
                           planned_risk=total_risk, risk_fraction=ratio(total_risk), positions=positions)
    current = metrics(s.cash, quantities, risks)
    cash = s.cash
    sell_reserved = {}
    for order in pending:
        if order.side == 'SELL':
            sell_reserved[order.ticker] = sell_reserved.get(order.ticker, 0) + order.quantity
    for ticker, qty in sell_reserved.items():
        if qty > quantities.get(ticker, 0):
            reasons.append('PENDING_OVERSELL: outstanding SELLs exceed current holdings')
    if p.side == 'SELL' and p.quantity + sell_reserved.get(p.ticker, 0) > quantities.get(p.ticker, 0):
        reasons.append('OVERSELL: proposed and outstanding SELLs exceed current holdings')
        return reasons, current, None
    # A pending SELL can consume cash if its commission exceeds proceeds.
    for order in pending:
        if order.side == 'SELL':
            cash -= max(Decimal(0), order.commission - order.quantity * (order.entry_price - order.slippage))
    # Sell only currently held shares before adding pending BUY risk tranches.
    orders = (p, *pending) if p.side == 'SELL' else (*pending, p)
    # Pending SELLs never fund buys or release risk/exposure capacity.
    for order in orders:
        if order.side == 'SELL' and order is not p:
            continue
        ticker, qty = order.ticker, order.quantity
        if order.side == 'BUY':
            execution = order.entry_price + order.slippage
            cash -= qty * execution + order.commission
            quantities[ticker] = quantities.get(ticker, 0) + qty
            # Protect both remaining marked downside and new entry-to-stop risk.
            risks[ticker] = risks.get(ticker, Decimal(0)) + qty * (
                max(execution, marks[ticker]) - order.stop_price + order.exit_slippage
            ) + order.commission + order.exit_commission
            if order.stop_price >= marks[ticker]:
                reasons.append('INVALID_STOP: BUY stop must be below current mark')
        else:
            held = quantities[ticker]
            cash += qty * (order.entry_price - order.slippage) - order.commission
            holding = next(h for h in s.holdings if h.ticker == ticker)
            risks[ticker] = (held - qty) * held_risk_per_share[ticker] + (
                holding.exit_commission if held > qty else Decimal(0))
            quantities[ticker] -= qty
    projected = metrics(cash, quantities, risks, current.equity)
    base = min(current.equity, projected.equity)
    if base <= 0: reasons.append('NONPOSITIVE_EQUITY: positive equity required')
    if cash < 0: reasons.append('NEGATIVE_CASH: no margin or borrowing permitted')
    limits = _exposure_risk_breaches(projected, c)
    # Only existing exposure/stop-risk breaches can be retained. Pending BUYs
    # cannot ride an exit exception into new capacity. Cash reserve and every
    # structural/integrity rejection remain mandatory, as do all BUY checks.
    owned = next((h.quantity for h in s.holdings if h.ticker == p.ticker), 0)
    reducing_sell = (p.side == 'SELL' and 0 <= quantities.get(p.ticker, 0) < owned
        and projected.invested < current.invested
        and projected.planned_risk <= current.planned_risk
        and not any(o.side == 'BUY' for o in pending))
    if reducing_sell:
        existing = set(_exposure_risk_breaches(current, c))
        limits = [reason for reason in limits if reason not in existing]
    # Keep the previous reason ordering for BUY audits/replay.
    reasons.extend(reason for reason in limits if reason.startswith('TOTAL_EXPOSURE:'))
    if cash < base * c.min_cash:
        reasons.append('CASH_RESERVE: minimum cash reserve breached')
    reasons.extend(reason for reason in limits if not reason.startswith('TOTAL_EXPOSURE:'))
    return list(dict.fromkeys(reasons)), current, projected


def size_pretrade_buy(snapshot: ValuationSnapshot, template: Proposal, configuration: RiskConfiguration,
                      *, evaluated_at: datetime) -> tuple[int, RiskDecision]:
    """Largest approved whole-share quantity up to the explicit proposal cap.

    Uses V1's floor/minimum-of-constraints convention, with explicit stops rather
    than inventing ATR. Evaluates all costs, existing holdings and pending orders.
    A rejected one-share proposal returns zero and its rejection audit.
    """
    template = Proposal.model_validate(template.model_dump(mode='json'))
    if template.side != 'BUY':
        raise ValueError('Position sizing requires a BUY proposal')
    one = template.model_copy(update={'quantity': 1})
    best = evaluate_pretrade(snapshot, one, configuration, evaluated_at=evaluated_at)
    if best.decision == 'REJECTED':
        return 0, best
    low, high = 1, template.quantity
    while low < high:
        middle = (low + high + 1) // 2
        decision = evaluate_pretrade(snapshot, template.model_copy(update={'quantity': middle}),
                                     configuration, evaluated_at=evaluated_at)
        if decision.decision == 'APPROVED':
            low, best = middle, decision
        else:
            high = middle - 1
    return low, best
