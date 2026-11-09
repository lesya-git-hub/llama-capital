"""Manually invoked synthetic fills under the broker's single SQLite write lock."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from tools.fx_conversion import (
    CanonicalFX, Digest, EURRiskInputs, FXInput, FXPolicy, RiskConversionRequest,
    USDHolding, convert_risk_inputs, replay_risk_inputs,
)
from tools.historical_snapshot import FrozenModel, canonical_json, input_hash
from tools.pretrade_risk import RiskConfiguration, RiskDecision, evaluate_pretrade


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False)


class LedgerState(FrozenModel):
    content: str  # Canonical full account, positions, orders and risk assumptions.


class ExecutionRequest(FXInput):
    schema_version: Literal[1] = 1
    mode: Literal['strict_synthetic'] = 'strict_synthetic'
    attempt_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    expected_state_sha256: Digest
    execution_at: AwareDatetime
    signal_available_at: AwareDatetime
    execution_price_at: AwareDatetime
    risk_inputs: RiskConversionRequest
    fx: CanonicalFX
    fx_policy: FXPolicy
    risk_policy: RiskConfiguration

    @model_validator(mode='after')
    def identity(self):
        if self.risk_inputs.proposal_usd.proposal_id != self.order_id:
            raise ValueError('Proposal ID must match the accepted broker order ID')
        return self


class ExecutionOutcome(FrozenModel):
    schema_version: Literal[1] = 1
    status: Literal['FILLED', 'REJECTED']
    request: ExecutionRequest
    request_sha256: Digest
    before: LedgerState
    after: LedgerState
    reasons: tuple[str, ...]
    risk: RiskDecision | None
    converted: EURRiskInputs | None
    fill_json: str | None
    execution_source_sha256: Digest


def replay_execution_checks(record: ExecutionOutcome, *, expected_sha256: str) -> ExecutionOutcome:
    """Offline audit/check replay, never a fill or historical-accounting rewrite.

    Financial reconstruction remains the broker's existing reconcile() method.
    Replaying an error record cannot prove that its recorded external error occurred.
    """
    record = ExecutionOutcome.model_validate(record.model_dump(mode='json'))
    if input_hash(record) != expected_sha256 or input_hash(record.request) != record.request_sha256:
        raise ValueError('Execution audit integrity mismatch')
    if record.execution_source_sha256 != source_hash():
        raise ValueError('Execution source differs from recorded implementation')
    if record.status == 'REJECTED' and (record.before != record.after or record.fill_json is not None):
        raise ValueError('Rejected outcome contains a financial mutation')
    if record.converted is not None:
        replay_risk_inputs(record.converted, expected_sha256=input_hash(record.converted))
        if (record.converted.request != record.request.risk_inputs
                or record.converted.fx != record.request.fx
                or record.converted.policy != record.request.fx_policy
                or record.converted.valuation_at != record.request.execution_at):
            raise ValueError('Converted source differs from execution request')
    if record.risk is not None:
        if record.converted is None:
            raise ValueError('Risk record lacks FX provenance')
        regenerated = evaluate_pretrade(record.converted.snapshot, record.converted.proposal,
            record.request.risk_policy, evaluated_at=record.request.execution_at)
        if regenerated != record.risk:
            raise ValueError('Execution risk audit differs from regenerated checks')
    if record.status == 'FILLED' and (record.risk is None or record.risk.decision != 'APPROVED'
                                    or record.fill_json is None):
        raise ValueError('Successful execution lacks risk/fill evidence')
    if record.status == 'FILLED':
        if input_hash(record.before) != record.request.expected_state_sha256:
            raise ValueError('Successful outcome used a stale state')
        fill = json.loads(record.fill_json)
        proposal = record.converted.proposal
        if ((fill['order_id'], fill['ticker'], fill['side'], fill['quantity']) !=
                (record.request.order_id, proposal.ticker, proposal.side, proposal.quantity)
                or Decimal(fill['reference_price']) != proposal.entry_price
                or Decimal(fill['commission']) != proposal.commission
                or Decimal(fill['slippage_per_share']) != proposal.slippage
                or datetime.fromisoformat(fill['timestamp']) != record.request.execution_at):
            raise ValueError('Recorded fill differs from checked instructions')
    return record


def source_hash():
    digest = sha256()
    root = Path(__file__).resolve().parents[1]
    for name in ('providers/paper_broker.py', 'tools/gated_execution.py', 'tools/operational_controls.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    return digest.hexdigest()


def read_state_locked(broker):
    if not broker._db.in_transaction:
        raise ValueError('Broker write transaction required')
    db = broker._db
    state = {}
    for table, ordering in (('account', 'id'), ('positions', 'ticker'), ('orders', 'order_id')):
        state[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY {ordering}')]
    state['audit_sequence'] = db.execute('SELECT COALESCE(MAX(sequence),0) FROM audit').fetchone()[0]
    state['strict'] = broker.strict
    if broker.strict:
        for table, ordering in (('gate_holdings', 'ticker'), ('gate_order_terms', 'order_id')):
            state[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY {ordering}')]
        from tools.operational_controls import read_control
        state['operational_control'] = read_control(db)
        state['operational_sequence'] = db.execute('SELECT COALESCE(MAX(sequence),0) FROM operational_events').fetchone()[0]
    return LedgerState(content=_json(state))


def load_attempt_locked(broker, attempt_id):
    row = broker._db.execute('SELECT * FROM gate_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
    if row is None:
        raise KeyError(attempt_id)
    outcome = ExecutionOutcome.model_validate_json(row['record_json'])
    if (input_hash(outcome) != row['record_sha256'] or input_hash(outcome.request) != row['request_sha256']
            or outcome.request.attempt_id != attempt_id or outcome.request.order_id != row['order_id']
            or outcome.status != row['outcome']):
        raise ValueError('Gated attempt integrity mismatch')
    return outcome


class GateRejected(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise GateRejected(message)


def execute_locked(broker, request):
    """Internal entry; broker owns BEGIN/COMMIT/ROLLBACK and dedicated connection."""
    if not broker._db.in_transaction or not broker.strict:
        raise ValueError('Strict broker write transaction required')
    db = broker._db
    request_hash = input_hash(request)
    previous = db.execute('SELECT request_sha256 FROM gate_attempts WHERE attempt_id=?', (request.attempt_id,)).fetchone()
    if previous:
        if previous[0] != request_hash:
            raise ValueError('Conflicting execution attempt identity')
        return load_attempt_locked(broker, request.attempt_id)
    # A nonexistent target cannot have a foreign-key-bound durable attempt.
    order = broker._order(request.order_id)
    before = read_state_locked(broker)
    risk, converted, fill_json = None, None, None
    reasons = ()
    db.execute('SAVEPOINT gated_financial_attempt')
    try:
        from tools.operational_controls import read_control
        _require(not read_control(db)['blocked'], 'OPERATIONAL_BLOCK: strict execution is latched off')
        _require(input_hash(before) == request.expected_state_sha256, 'STALE_STATE: ledger changed since the supplied state')
        _require(order.status == 'ACCEPTED', 'ORDER_STATUS: only an unfilled ACCEPTED order may execute')
        _require(request.execution_at > request.signal_available_at, 'LOOKAHEAD: execution must follow signal availability')
        _require(request.execution_price_at == request.execution_at, 'EXECUTION_PRICE_TIME: explicit synthetic fill price must be for execution time')
        state = json.loads(before.content)
        account = state['account'][0]
        _require(not account['killed'], 'KILL_SWITCH: execution is disabled')
        source = request.risk_inputs
        target = source.proposal_usd
        _require((target.ticker, target.side, target.quantity) == (order.ticker, order.side, order.quantity),
                 'ORDER_CONFLICT: proposal differs from broker instructions')
        _require(source.cash_eur == Decimal(account['cash']), 'STALE_CASH: supplied cash differs from locked ledger')
        live = {p['ticker']: p['quantity'] for p in state['positions']}
        supplied = {h.ticker: h.quantity for h in source.holdings_usd}
        _require(len(source.holdings_usd) == len(live) and supplied == live,
                 'HOLDING_COVERAGE: exact current holdings required')
        pending = {o['order_id']: o for o in state['orders']
                   if o['status'] in ('CREATED', 'ACCEPTED') and o['order_id'] != order.order_id}
        supplied_pending = {o.order.proposal_id: o for o in source.outstanding_usd}
        _require(len(source.outstanding_usd) == len(pending) and set(pending) == set(supplied_pending),
                 'PENDING_COVERAGE: exact outstanding-order assumptions required')
        for identity, row in pending.items():
            item = supplied_pending[identity]
            _require((item.order.ticker, item.order.side, item.order.quantity, item.status) ==
                     (row['ticker'], row['side'], row['quantity'], row['status']),
                     'PENDING_CONFLICT: outstanding instructions/status differ')
        # Successful gate attempts freeze USD stops/cost assumptions; later
        # requests cannot erase risk by silently replacing them.
        stored_holdings = {r['ticker']: r['terms_json'] for r in state['gate_holdings']}
        _require(set(stored_holdings) == set(live), 'HOLDING_PROVENANCE: missing persisted stop assumptions')
        for holding in source.holdings_usd:
            terms = holding.model_dump(mode='json')
            del terms['quantity']
            _require(_json(terms) == stored_holdings[holding.ticker], 'STOP_CONFLICT: held stop/cost assumptions cannot silently change')
        all_orders = (target, *(o.order for o in source.outstanding_usd))
        for item in all_orders:
            prior = db.execute('SELECT terms_json FROM gate_order_terms WHERE order_id=?', (item.proposal_id,)).fetchone()
            _require(prior is None or prior[0] == canonical_json(item), 'TERMS_CONFLICT: previously frozen USD instructions changed')
        if target.side == 'BUY' and target.ticker in live:
            held = next(h for h in source.holdings_usd if h.ticker == target.ticker)
            _require((held.stop_price, held.exit_slippage) == (target.stop_price, target.exit_slippage),
                     'TOPUP_STOP_CONFLICT: topping up requires the existing protective stop/slippage')
        converted = convert_risk_inputs(source, request.fx, request.fx_policy, valuation_at=request.execution_at)
        risk = evaluate_pretrade(converted.snapshot, converted.proposal, request.risk_policy,
                                 evaluated_at=request.execution_at)
        _require(risk.decision == 'APPROVED', 'RISK_REJECTED: ' + '; '.join(risk.reasons))
        eur = converted.proposal
        from providers.paper_broker import _timestamp
        broker._gate_active = True
        try:
            fill, blocked = broker._simulate_fill_locked(order.order_id, eur.entry_price, eur.commission,
                                                         eur.slippage, _timestamp(request.execution_at))
        finally:
            broker._gate_active = False
        _require(blocked is None, 'BROKER_REJECTED: ' + str(blocked))
        fill_json = _json(asdict(fill))
        for item in all_orders:
            db.execute('INSERT OR IGNORE INTO gate_order_terms VALUES (?,?)', (item.proposal_id, canonical_json(item)))
        quantity = live.get(target.ticker, 0) + (target.quantity if target.side == 'BUY' else -target.quantity)
        if quantity:
            if target.side == 'BUY':
                old = next((h for h in source.holdings_usd if h.ticker == target.ticker), None)
                held = USDHolding(ticker=target.ticker, quantity=quantity, stop_price=target.stop_price,
                    exit_slippage=target.exit_slippage,
                    exit_commission=target.exit_commission + (old.exit_commission if old else Decimal(0)))
            else:
                old = next(h for h in source.holdings_usd if h.ticker == target.ticker)
                held = old.model_copy(update={'quantity': quantity})
            terms = held.model_dump(mode='json')
            del terms['quantity']
            db.execute('INSERT INTO gate_holdings VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET terms_json=excluded.terms_json',
                       (target.ticker, _json(terms)))
        else:
            db.execute('DELETE FROM gate_holdings WHERE ticker=?', (target.ticker,))
        after = read_state_locked(broker)
        status = 'FILLED'
        db.execute('RELEASE gated_financial_attempt')
    except Exception as exc:
        # If rollback itself fails, propagate: the broker outer transaction
        # rolls back. Never commit a rejection after an unconfirmed rollback.
        db.execute('ROLLBACK TO gated_financial_attempt')
        db.execute('RELEASE gated_financial_attempt')
        after = read_state_locked(broker)
        if after != before:
            raise RuntimeError('Financial rollback could not be verified') from exc
        fill_json = None
        status = 'REJECTED'
        reasons = (str(exc) if isinstance(exc, GateRejected) else f'EXECUTION_FAILED: {type(exc).__name__}: {exc}',)
    record = ExecutionOutcome(status=status, request=request, request_sha256=request_hash,
        before=before, after=after, reasons=reasons or ('RISK_APPROVED_AND_FILLED',), risk=risk,
        converted=converted, fill_json=fill_json, execution_source_sha256=source_hash())
    # Outside savepoint, still inside the SAME write transaction. Audit failure
    # propagates to the outer rollback, including any successful financial fill.
    db.execute('INSERT INTO gate_attempts VALUES (?,?,?,?,?,?)',
               (request.attempt_id, request.order_id, request_hash, status, input_hash(record), canonical_json(record)))
    return record
