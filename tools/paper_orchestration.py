"""Explicit PREVIEW/EXECUTE for synthetic, independently gated paper orders."""

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from models.daily_signals import DAILY_UNIVERSE, DailyDecision
from tools.fx_conversion import (CanonicalFX, Digest, EURRiskInputs, FXInput, FXPolicy,
    RiskConversionRequest, USDHolding, USDOutstanding, USDProposal, convert_risk_inputs, validate_quote)
from tools.gated_execution import ExecutionOutcome, ExecutionRequest, LedgerState, replay_execution_checks
from tools.historical_snapshot import FrozenModel, canonical_json, input_hash
from tools.market_verification import CalendarArtifact, TrustRegistry
from tools.pretrade_risk import RiskConfiguration, RiskDecision, RiskMetrics, evaluate_pretrade
from tools.verified_daily_pipeline import VerifiedDailyInputs, VerifiedDailyReport, replay_verified_daily_signals


class TradeIntent(FXInput):
    signal_sha256: Digest
    order: USDProposal  # Existing manually staged ACCEPTED broker instruction.
    execution_at: AwareDatetime
    execution_price_at: AwareDatetime
    price_available_at: AwareDatetime
    fx: CanonicalFX
    fx_policy: FXPolicy
    risk_policy: RiskConfiguration


class WorkflowInput(FXInput):
    scope: Literal['synthetic_test'] = 'synthetic_test'
    run_id: str = Field(min_length=1)
    signals: VerifiedDailyInputs
    signals_sha256: Digest
    execution_calendar: CalendarArtifact
    variant: Literal['baseline', 'bear_filtered']
    context: RiskConversionRequest
    intents: tuple[TradeIntent, ...]
    transition_policy: Literal['carry_forward_only_own_gate_outcomes_v1'] = 'carry_forward_only_own_gate_outcomes_v1'

    @model_validator(mode='after')
    def unique(self):
        if (len({i.order.ticker for i in self.intents}) != len(self.intents)
                or len({i.order.proposal_id for i in self.intents}) != len(self.intents)):
            raise ValueError('One explicit trade per ticker/order per workflow required')
        if any(i.order.ticker not in DAILY_UNIVERSE for i in self.intents):
            raise ValueError('Six-stock universe only')
        context_tickers = ({h.ticker for h in self.context.holdings_usd} | {m.ticker for m in self.context.marks_usd}
            | {o.order.ticker for o in self.context.outstanding_usd} | {self.context.proposal_usd.ticker})
        if context_tickers - set(DAILY_UNIVERSE):
            raise ValueError('Source valuation and pending assumptions must use the six-stock universe')
        if any(b.execution_at < a.execution_at for a, b in zip(self.intents, self.intents[1:])):
            raise ValueError('Explicit execution sequence must be chronological')
        if self.signals.scope != 'synthetic_test' or self.execution_calendar.scope != 'synthetic_test':
            raise ValueError('Production-verified orchestration is blocked; synthetic scope required')
        return self


class PreviewStep(FrozenModel):
    signal: DailyDecision
    signal_sha256: Digest
    status: Literal['PROPOSED', 'REJECTED', 'SKIPPED']
    reasons: tuple[str, ...]
    request: ExecutionRequest | None
    converted: EURRiskInputs | None
    advisory_risk: RiskDecision | None


class WorkflowPreview(FrozenModel):
    input: WorkflowInput
    input_sha256: Digest
    preview_at: AwareDatetime
    initial_state: LedgerState
    ledger_identity: str
    signals: VerifiedDailyReport
    steps: tuple[PreviewStep, ...]
    trust_sha256: Digest
    orchestration_sha256: Digest


class Authorization(FXInput):
    purpose: Literal['execute_synthetic_workflow']
    run_id: str = Field(min_length=1)
    preview_sha256: Digest
    authorization_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    authorized_at: AwareDatetime


class WorkflowStep(FrozenModel):
    signal_sha256: Digest
    order_id: str | None
    status: Literal['FILLED', 'REJECTED', 'SKIPPED', 'ERROR']
    reasons: tuple[str, ...]
    outcome: ExecutionOutcome | None = None
    outcome_sha256: Digest | None = None


class WorkflowReport(FrozenModel):
    run_id: str
    status: Literal['COMPLETED', 'PARTIAL', 'REJECTED', 'INTERRUPTED']
    preview_sha256: Digest
    authorization: Authorization
    authorization_sha256: Digest
    steps: tuple[WorkflowStep, ...]
    final_state: LedgerState
    final_cash_eur: Decimal
    final_metrics: RiskMetrics | None
    warning: str = 'SYNTHETIC simulation only; independently gated orders, partial execution possible; not investment performance.'


def source_hash():
    return sha256(Path(__file__).read_bytes()).hexdigest()


def _ledger_identity(broker):
    # Read-only SQLite connection metadata, not financial-table access/mutation.
    filename = next(r[2] for r in broker._db.execute('PRAGMA database_list') if r[1] == 'main')
    if not filename:
        raise ValueError('Restart-safe orchestration requires a file-backed strict ledger')
    return os.path.normcase(str(Path(filename).resolve()))


def _templates(plan):
    result = {}
    for order in (plan.context.proposal_usd, *(p.order for p in plan.context.outstanding_usd),
                  *(i.order for i in plan.intents)):
        if order.proposal_id in result and result[order.proposal_id] != order:
            raise ValueError('Conflicting supplied USD order assumptions')
        result[order.proposal_id] = order
    return result


def _request(plan, intent, signal, state):
    raw = json.loads(state.content)
    orders = {o['order_id']: o for o in raw['orders']}
    identity = intent.order.proposal_id
    if identity not in orders:
        raise ValueError('Manually staged broker order is missing')
    row = orders[identity]
    if (row['ticker'], row['side'], row['quantity']) != (intent.order.ticker, intent.order.side, intent.order.quantity):
        raise ValueError('Broker order conflicts with intent')
    templates = _templates(plan)
    pending = []
    for other in raw['orders']:
        if other['status'] in ('CREATED', 'ACCEPTED') and other['order_id'] != identity:
            if other['order_id'] not in templates:
                raise ValueError('Missing outstanding-order assumptions')
            pending.append(USDOutstanding(order=templates[other['order_id']], status=other['status']))
    terms = {h['ticker']: json.loads(h['terms_json']) for h in raw.get('gate_holdings', ())}
    holdings = tuple(USDHolding(**(terms[p['ticker']] | {'quantity': p['quantity']})) for p in raw['positions'])
    # This reads prior committed gate metadata. It performs no accounting or
    # guessed updates of cash, quantities, stops or order lifecycle.
    context = plan.context.model_copy(update={'cash_eur': Decimal(raw['account'][0]['cash']),
        'holdings_usd': holdings, 'outstanding_usd': tuple(pending), 'proposal_usd': intent.order})
    context = RiskConversionRequest.model_validate(context.model_dump(mode='json'))
    return ExecutionRequest(attempt_id=f'workflow:{plan.run_id}:{input_hash(plan)}:{identity}',
        order_id=identity, expected_state_sha256=input_hash(state), execution_at=intent.execution_at,
        signal_available_at=signal.decision_at, execution_price_at=intent.execution_price_at,
        risk_inputs=context, fx=intent.fx, fx_policy=intent.fx_policy, risk_policy=intent.risk_policy)


def _preview(plan, state, preview_at, trust, ledger_identity):
    plan = WorkflowInput.model_validate(plan.model_dump(mode='json'))
    if not isinstance(preview_at, datetime) or preview_at.tzinfo is None or preview_at.utcoffset() is None:
        raise ValueError('Explicit aware preview timestamp required')
    preview_at = preview_at.astimezone(timezone.utc)
    trust = TrustRegistry.model_validate(trust.model_dump(mode='json'))
    if trust.mode != 'synthetic_test':
        raise ValueError('Explicit external synthetic trust root required; production registry remains empty')
    trust.require(plan.execution_calendar, 'calendar')
    signals = replay_verified_daily_signals(plan.signals, expected_sha256=plan.signals_sha256, trust=trust)
    decisions = tuple(d for d in signals.daily_report.decisions if d.variant == plan.variant)
    if len(decisions) != 6 or {d.ticker for d in decisions} != set(DAILY_UNIVERSE):
        raise ValueError('Exact six-stock signal universe required')
    if preview_at < signals.daily_report.decision_at:
        raise ValueError('Preview predates signal availability')
    raw = json.loads(state.content)
    if not raw['strict']:
        raise ValueError('Strict ledger required')
    if plan.context.cash_eur != Decimal(raw['account'][0]['cash']):
        raise ValueError('Initial source cash differs from preview ledger')
    if (len(plan.context.holdings_usd) != len(raw['positions'])
            or {h.ticker: h.quantity for h in plan.context.holdings_usd} != {h['ticker']: h['quantity'] for h in raw['positions']}):
        raise ValueError('Initial holdings differ from preview ledger')
    stored_terms = {h['ticker']: json.loads(h['terms_json']) for h in raw.get('gate_holdings', ())}
    for holding in plan.context.holdings_usd:
        data = holding.model_dump(mode='json')
        del data['quantity']
        if stored_terms.get(holding.ticker) != data:
            raise ValueError('Initial stop assumptions differ from persisted gate metadata')
    if plan.context.as_of > preview_at:
        raise ValueError('Valuation source is unavailable at preview')
    _templates(plan)
    by_ticker = {d.ticker: d for d in decisions}
    steps = []
    # Explicit supplied order is execution order; no implicit BUY/SELL priority.
    tickers = [i.order.ticker for i in plan.intents] + sorted(set(DAILY_UNIVERSE) - {i.order.ticker for i in plan.intents})
    intents = {i.order.ticker: i for i in plan.intents}
    listings = {p.ticker: p.exchange for p in plan.execution_calendar.listings}
    for ticker in tickers:
        signal, intent = by_ticker[ticker], intents.get(ticker)
        request, converted, risk = None, None, None
        status, reasons = 'SKIPPED', ('NO_MANUAL_TRADE',)
        if intent is not None:
            try:
                if input_hash(signal) != intent.signal_sha256:
                    raise ValueError('Signal identity mismatch')
                if signal.decision == 'HOLD':
                    reasons = ('HOLD: no execution instruction',)
                else:
                    if intent.order.side != signal.decision:
                        raise ValueError('Manual trade side conflicts with selected signal')
                    if not intent.price_available_at <= preview_at <= intent.execution_at:
                        raise ValueError('Execution price unavailable at preview or execution predates preview')
                    if intent.execution_at <= signal.decision_at or intent.execution_price_at != intent.execution_at:
                        raise ValueError('LOOKAHEAD: execution must follow signal availability with explicit execution price time')
                    if plan.execution_calendar.available_at > preview_at:
                        raise ValueError('Execution calendar unavailable at preview')
                    validate_quote(intent.fx, intent.fx_policy, valuation_at=preview_at)
                    sessions = [s for s in plan.execution_calendar.sessions if s.exchange == listings[ticker]
                                and s.opens_at <= intent.execution_at < s.closes_at and s.date > signal.signal_date]
                    if len(sessions) != 1:
                        raise ValueError('Explicit later execution session required; same-close execution prohibited')
                    request = _request(plan, intent, signal, state)
                    order = next(o for o in raw['orders'] if o['order_id'] == request.order_id)
                    if order['status'] != 'ACCEPTED':
                        raise ValueError('Manually staged ACCEPTED order required')
                    converted = convert_risk_inputs(request.risk_inputs, request.fx, request.fx_policy,
                                                    valuation_at=request.execution_at)
                    risk = evaluate_pretrade(converted.snapshot, converted.proposal, request.risk_policy,
                                             evaluated_at=request.execution_at)
                    if raw['account'][0]['killed']:
                        raise ValueError('KILL_SWITCH: execution disabled')
                    status = 'PROPOSED' if risk.decision == 'APPROVED' else 'REJECTED'
                    reasons = ('PREVIEW_ONLY: final risk is evaluated under the broker write lock',) if status == 'PROPOSED' else risk.reasons
            except (ValueError, KeyError) as exc:
                status, reasons = 'REJECTED', (str(exc),)
        steps.append(PreviewStep(signal=signal, signal_sha256=input_hash(signal), status=status,
            reasons=reasons, request=request, converted=converted, advisory_risk=risk))
    return WorkflowPreview(input=plan, input_sha256=input_hash(plan), preview_at=preview_at,
        initial_state=state, ledger_identity=ledger_identity, signals=signals, steps=tuple(steps), trust_sha256=input_hash(trust),
        orchestration_sha256=source_hash())


class WorkflowStore:
    """Separate workflow journal. Broker gate remains financial commit authority."""
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            app = db.execute('PRAGMA application_id').fetchone()[0]
            if not tables and not app:
                db.execute('PRAGMA application_id=1280070487')
                db.execute('PRAGMA user_version=1')
                db.execute('CREATE TABLE previews (run_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content TEXT NOT NULL)')
                db.execute('CREATE TABLE authorizations (run_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content TEXT NOT NULL)')
                db.execute('CREATE TABLE steps (run_id TEXT NOT NULL, order_id TEXT NOT NULL, request_sha256 TEXT NOT NULL, request_json TEXT NOT NULL, outcome_sha256 TEXT, outcome_json TEXT, PRIMARY KEY(run_id,order_id))')
                db.execute('CREATE TABLE reports (sha256 TEXT PRIMARY KEY, run_id TEXT NOT NULL, content TEXT NOT NULL)')
            elif app != 1280070487 or db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('Not a supported workflow journal')

    def _immutable(self, table, run_id, value):
        content, digest = canonical_json(value), input_hash(value)
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute(f'SELECT sha256,content FROM {table} WHERE run_id=?', (run_id,)).fetchone()
            if old is not None and old != (digest, content):
                raise ValueError('Workflow identity conflicts with persisted content')
            if old is None:
                db.execute(f'INSERT INTO {table} VALUES (?,?,?)', (run_id, digest, content))

    def load_preview(self, run_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT sha256,content FROM previews WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        result = WorkflowPreview.model_validate_json(row[1])
        if input_hash(result) != row[0] or result.input.run_id != run_id:
            raise ValueError('Preview journal integrity mismatch')
        return result

    def _step(self, run_id, request, outcome=None):
        digest, content = input_hash(request), canonical_json(request)
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM steps WHERE run_id=? AND order_id=?', (run_id, request.order_id)).fetchone()
            if row is not None and row[2:4] != (digest, content):
                raise ValueError('Prepared workflow request conflicts with journal')
            if row is None:
                db.execute('INSERT INTO steps VALUES (?,?,?,?,NULL,NULL)', (run_id, request.order_id, digest, content))
            if outcome is not None:
                if row is not None and row[4] is not None and row[4:] != (input_hash(outcome), canonical_json(outcome)):
                    raise ValueError('Workflow outcome conflicts with journal')
                db.execute('UPDATE steps SET outcome_sha256=?,outcome_json=? WHERE run_id=? AND order_id=?',
                    (input_hash(outcome), canonical_json(outcome), run_id, request.order_id))

    def save_report(self, report):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?)', (input_hash(report), report.run_id, canonical_json(report)))

    def load_report(self, *, expected_sha256):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT content FROM reports WHERE sha256=?', (expected_sha256,)).fetchone()
        if row is None:
            raise KeyError(expected_sha256)
        report = WorkflowReport.model_validate_json(row[0])
        if input_hash(report) != expected_sha256:
            raise ValueError('Workflow report integrity mismatch')
        return report


def preview_workflow(plan, *, broker, store, preview_at, trust=TrustRegistry()):
    if not broker.strict:
        raise ValueError('Strict ledger required')
    result = _preview(plan, broker.execution_state(), preview_at, trust, _ledger_identity(broker))
    store._immutable('previews', plan.run_id, result)
    return result


def replay_preview(preview, *, expected_sha256, trust=TrustRegistry()):
    preview = WorkflowPreview.model_validate(preview.model_dump(mode='json'))
    if input_hash(preview) != expected_sha256:
        raise ValueError('Preview integrity mismatch')
    regenerated = _preview(preview.input, preview.initial_state, preview.preview_at, trust, preview.ledger_identity)
    if regenerated != preview:
        raise ValueError('Preview replay differs from persisted inputs/checks')
    return regenerated


def execute_workflow(run_id, *, authorization, broker, store, trust=TrustRegistry()):
    if authorization is None:
        raise ValueError('Explicit manual authorization required')
    authorization = Authorization.model_validate(authorization.model_dump(mode='json'))
    if not broker.strict:
        raise ValueError('Strict ledger required')
    preview = store.load_preview(run_id)
    if _ledger_identity(broker) != preview.ledger_identity:
        raise ValueError('Authorization targets a different strict ledger')
    digest = input_hash(preview)
    if authorization.run_id != run_id or authorization.preview_sha256 != digest:
        raise ValueError('Authorization does not match the exact proposal identity')
    replay_preview(preview, expected_sha256=digest, trust=trust)
    if authorization.authorized_at < preview.preview_at or any(
        authorization.authorized_at > s.request.execution_at for s in preview.steps if s.status == 'PROPOSED'):
        raise ValueError('Authorization timing violates preview/execution ordering')
    store._immutable('authorizations', run_id, authorization)
    expected = preview.initial_state
    results, halted = [], False
    intents = {i.order.ticker: i for i in preview.input.intents}
    for step in preview.steps:
        identity = intents[step.signal.ticker].order.proposal_id if step.signal.ticker in intents else None
        if step.status != 'PROPOSED' or halted:
            results.append(WorkflowStep(signal_sha256=step.signal_sha256, order_id=identity,
                status='SKIPPED' if halted or step.status == 'SKIPPED' else 'REJECTED',
                reasons=('NOT_ATTEMPTED_AFTER_INTERRUPTION',) if halted else step.reasons))
            continue
        try:
            req = _request(preview.input, intents[step.signal.ticker], step.signal, expected)
            # Commit intent BEFORE calling the independently committing broker.
            store._step(run_id, req)
            try:
                outcome = broker.execution_attempt(req.attempt_id)
            except KeyError:
                outcome = broker.execute_gated(req)
            if outcome.request_sha256 != input_hash(req):
                raise ValueError('Broker audit reference conflicts with prepared workflow request')
            replay_execution_checks(outcome, expected_sha256=input_hash(outcome))
            store._step(run_id, req, outcome)
            results.append(WorkflowStep(signal_sha256=step.signal_sha256, order_id=identity,
                status=outcome.status, reasons=outcome.reasons, outcome=outcome, outcome_sha256=input_hash(outcome)))
            if outcome.before != expected:
                halted = True  # Never adopt an unrelated external portfolio change.
            else:
                expected = outcome.after
        except Exception as exc:
            halted = True
            results.append(WorkflowStep(signal_sha256=step.signal_sha256, order_id=identity,
                status='ERROR', reasons=(f'{type(exc).__name__}: {exc}',)))
    final = broker.execution_state()
    cash = Decimal(json.loads(final.content)['account'][0]['cash'])
    metrics = None
    if preview.input.intents and final == expected and not halted:
        try:
            item = preview.input.intents[-1]
            decision = next(s.signal for s in preview.steps if s.signal.ticker == item.order.ticker)
            req = _request(preview.input, item, decision, final)
            converted = convert_risk_inputs(req.risk_inputs, req.fx, req.fx_policy, valuation_at=req.execution_at)
            metrics = evaluate_pretrade(converted.snapshot, converted.proposal, req.risk_policy,
                                       evaluated_at=req.execution_at).current
        except (ValueError, KeyError):
            pass  # Missing/stale valuations never become invented final exposure.
    filled = sum(s.status == 'FILLED' for s in results)
    status = ('INTERRUPTED' if any(s.status == 'ERROR' for s in results) else
              'PARTIAL' if filled and any(s.status == 'REJECTED' for s in results) else
              'REJECTED' if not filled and any(s.status == 'REJECTED' for s in results) else 'COMPLETED')
    report = WorkflowReport(run_id=run_id, status=status, preview_sha256=digest, authorization=authorization,
        authorization_sha256=input_hash(authorization), steps=tuple(results), final_state=final,
        final_cash_eur=cash, final_metrics=metrics)
    store.save_report(report)
    return report


def replay_workflow_report(report, *, expected_sha256, preview, trust=TrustRegistry()):
    report = WorkflowReport.model_validate(report.model_dump(mode='json'))
    if input_hash(report) != expected_sha256:
        raise ValueError('Workflow report integrity mismatch')
    replay_preview(preview, expected_sha256=report.preview_sha256, trust=trust)
    if (report.run_id != preview.input.run_id or report.authorization.run_id != report.run_id
            or report.authorization.preview_sha256 != report.preview_sha256
            or input_hash(report.authorization) != report.authorization_sha256):
        raise ValueError('Workflow authorization reference mismatch')
    if tuple(s.signal_sha256 for s in report.steps) != tuple(s.signal_sha256 for s in preview.steps):
        raise ValueError('Workflow signal coverage differs from preview')
    expected, halted = preview.initial_state, False
    intents = {i.order.ticker: i for i in preview.input.intents}
    for step, original in zip(report.steps, preview.steps):
        if step.status == 'FILLED' and step.outcome is None:
            raise ValueError('Filled workflow step lacks broker audit')
        if step.outcome is not None:
            if halted:
                raise ValueError('Workflow continued execution after an interrupted state chain')
            replay_execution_checks(step.outcome, expected_sha256=step.outcome_sha256)
            if step.order_id != step.outcome.request.order_id or step.status != step.outcome.status:
                raise ValueError('Workflow broker audit reference mismatch')
            if (original.status != 'PROPOSED' or step.outcome.request.signal_available_at != original.signal.decision_at
                    or original.request is None or step.outcome.request.attempt_id != original.request.attempt_id):
                raise ValueError('Workflow outcome is not tied to the authorized signal/proposal')
            request = _request(preview.input, intents[original.signal.ticker], original.signal, expected)
            if step.outcome.request != request:
                raise ValueError('Workflow execution differs from authorized state-transition policy')
            if step.outcome.before == expected:
                expected = step.outcome.after
            else:
                halted = True
        if step.status == 'ERROR':
            halted = True
    if Decimal(json.loads(report.final_state.content)['account'][0]['cash']) != report.final_cash_eur:
        raise ValueError('Workflow final cash differs from captured ledger')
    return report


def human_preview(preview):
    lines = [f'Workflow {preview.input.run_id}: PREVIEW ONLY',
        'SYNTHETIC fixtures; no orders created or fills issued. Explicit authorization required.',
        f'Proposal identity: {input_hash(preview)}; input snapshot: {preview.input_sha256}']
    for step in preview.steps:
        trade = step.request.risk_inputs.proposal_usd if step.request else None
        description = f'{trade.side} {trade.quantity} {trade.ticker} USD {trade.entry_price}' if trade else 'none'
        risk = step.advisory_risk.decision if step.advisory_risk else 'not evaluated'
        lines.append(f'{step.signal.ticker}: {step.signal.decision}; {step.status}; proposed={description}; advisory risk={risk}; {"; ".join(step.reasons)}')
    return '\n'.join(lines)


def human_report(report, preview=None):
    counts = {s: sum(row.status == s for row in report.steps) for s in ('FILLED', 'REJECTED', 'SKIPPED', 'ERROR')}
    lines = [f'Workflow {report.run_id}: {report.status}', report.warning,
        ', '.join(f'{s.lower()}={n}' for s, n in counts.items()), f'EUR cash: {report.final_cash_eur}',
        f'Authorization: {report.authorization.authorization_id}; preview: {report.preview_sha256}']
    if report.final_metrics is not None:
        lines.append(f'Marked exposure EUR: {report.final_metrics.invested}; equity EUR: {report.final_metrics.equity}')
        lines.extend(f'Position {p.ticker}: EUR {p.value}; equity fraction={p.concentration}'
                     for p in report.final_metrics.positions)
    for row in report.steps:
        ref = row.outcome.request.attempt_id if row.outcome else 'none'
        fx = row.outcome.request.fx.source_quote.quote_id if row.outcome else 'none'
        risk = row.outcome.risk.decision if row.outcome and row.outcome.risk else 'not evaluated'
        request = row.outcome.request if row.outcome else None
        if request is None and preview is not None:
            request = next((s.request for s in preview.steps if s.signal_sha256 == row.signal_sha256), None)
        if request is not None:
            fx = f'{request.fx.source_quote.quote_id} {request.fx.direction}={request.fx.rate}'
        trade = request.risk_inputs.proposal_usd if request else None
        proposed = f'{trade.side} {trade.quantity} {trade.ticker} at USD {trade.entry_price}' if trade else 'none'
        lines.append(f'{row.order_id or row.signal_sha256}: {row.status}; proposed={proposed}; risk={risk}; FX={fx}; audit={ref}; {"; ".join(row.reasons)}')
    return '\n'.join(lines)
