from datetime import datetime, timedelta, time, timezone
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3

import pytest

from tests.test_market_verification import fixture, registry
from models.daily_signals import ObservedTicker
from providers.paper_broker import PaperBroker
from tools.fx_conversion import (FXQuote, FXPolicy, USDProposal, USDMark, USDHolding,
    USDOutstanding, RiskConversionRequest, canonical_quote)
from tools.historical_snapshot import Candle, canonical_json, input_hash
from tools.market_verification import (CalendarArtifact, ExchangeSession, ProviderEvidenceArtifact,
    TrustPin, TrustRegistry, VerificationPolicy)
from tools.pretrade_risk import RiskConfiguration
from tools.verified_daily_pipeline import freeze_verified_daily_inputs, replay_verified_daily_signals
from tools.paper_orchestration import (Authorization, TradeIntent, WorkflowInput, WorkflowStore,
    execute_workflow, preview_workflow, replay_preview, replay_workflow_report, human_preview, human_report)


@pytest.fixture(scope='module')
def signals(fixture):
    calendar, original, evidence, verified, decision = fixture
    observed = []
    for o in original:
        data = o.model_dump(mode='json')
        if o.snapshot.ticker in ('AAPL', 'MSFT'):
            # Invented declining history and rebound trigger the unchanged V1 BUY.
            prices = list(range(99, 85, -1)) + [92]
            for b, price in zip(data['snapshot']['bars'][-15:], prices):
                b.update(open=price, close=price, high=price + 1, low=price - 1)
        observed.append(ObservedTicker.model_validate(data))
    hashes = {(o.snapshot.ticker, b.date): input_hash(b) for o in observed for b in o.snapshot.bars}
    data = evidence.model_dump(mode='python')
    data['candles'] = tuple(e.model_copy(update={'candle_sha256': hashes[(e.ticker, e.date)]}) for e in evidence.candles)
    evidence = ProviderEvidenceArtifact.model_validate(data)
    trust = registry(calendar, evidence)
    inputs = freeze_verified_daily_inputs(calendar, tuple(observed), evidence,
        policy=VerificationPolicy(publication_delay_seconds=600), verified_at=verified,
        decision_at=decision, trust=trust)
    report = replay_verified_daily_signals(inputs, expected_sha256=input_hash(inputs), trust=trust)
    assert {d.decision for d in report.daily_report.decisions if d.ticker == 'AAPL' and d.variant == 'baseline'} == {'BUY'}
    day = calendar.coverage_end
    start = datetime.combine(day, time(14, 30), timezone.utc)
    execution = CalendarArtifact(schema_version=1, scope='synthetic_test', source='SYNTHETIC-EXECUTION',
        version='fixture-1', available_at=calendar.available_at, coverage_start=day,
        coverage_end=day + timedelta(days=1), listings=calendar.listings,
        sessions=tuple(ExchangeSession(date=day, exchange=e, source='SYNTHETIC-EXECUTION', version='fixture-1',
            opens_at=start, closes_at=start + timedelta(hours=6, minutes=30)) for e in ('XNAS', 'XNYS')),
        closed_dates=())
    trust = trust.model_copy(update={'pins': (*trust.pins, TrustPin(kind='calendar', scope='synthetic_test',
        source=execution.source, version=execution.version, sha256=input_hash(execution), review_reference='SYNTHETIC TEST ONLY'))})
    # 1C binds the EXACT external registry, including execution-calendar pins.
    inputs = freeze_verified_daily_inputs(calendar, tuple(observed), evidence,
        policy=VerificationPolicy(publication_delay_seconds=600), verified_at=verified,
        decision_at=decision, trust=trust)
    report = replay_verified_daily_signals(inputs, expected_sha256=input_hash(inputs), trust=trust)
    return inputs, report, execution, trust, start + timedelta(minutes=30)


def staged(broker, now, identity='a', ticker='AAPL', side='BUY', qty=10):
    broker.create_order(identity, ticker, side, qty, timestamp=now - timedelta(seconds=2))
    broker.accept_order(identity, timestamp=now - timedelta(seconds=1))


def proposal(identity='a', ticker='AAPL', side='BUY', qty=10):
    return USDProposal(proposal_id=identity, ticker=ticker, side=side, quantity=qty,
        entry_price='100', stop_price='95', commission='0', slippage='0', exit_commission='0', exit_slippage='0')


def plan(broker, signals, orders=None, run='workflow'):
    inputs, report, calendar, trust, now = signals
    orders = orders or (proposal(),)
    state = json.loads(broker.execution_state().content)
    terms = {r['ticker']: json.loads(r['terms_json']) for r in state.get('gate_holdings', ())}
    holdings = tuple(USDHolding(**(terms[r['ticker']] | {'quantity': r['quantity']})) for r in state['positions'])
    all_tickers = {p.ticker for p in orders} | {h.ticker for h in holdings}
    context = RiskConversionRequest(snapshot_id='synthetic', source='fixture', as_of=now,
        cash_eur=state['account'][0]['cash'], holdings_usd=holdings,
        marks_usd=tuple(USDMark(ticker=t, price='100', as_of=now) for t in sorted(all_tickers)),
        proposal_usd=orders[0], outstanding_usd=tuple(USDOutstanding(order=o, status='ACCEPTED') for o in orders[1:]))
    quote = canonical_quote(FXQuote(scope='synthetic_test', pair='USD_EUR', direction='EUR_PER_USD', rate='1',
        effective_at=now, retrieved_at=now, provider_id='SYNTHETIC', dataset_id='fixture', quote_id='q1',
        payload_sha256=sha256(b'fixture').hexdigest(), price_convention='indicative_mid', provenance='TEST ONLY'))
    selected = {d.ticker: d for d in report.daily_report.decisions if d.variant == 'baseline'}
    intents = tuple(TradeIntent(signal_sha256=input_hash(selected[o.ticker]), order=o, execution_at=now,
        execution_price_at=now, price_available_at=now, fx=quote, fx_policy=FXPolicy(max_age_seconds=60),
        risk_policy=RiskConfiguration(max_age_seconds=60)) for o in orders)
    return WorkflowInput(run_id=run, signals=inputs, signals_sha256=input_hash(inputs), execution_calendar=calendar,
        variant='baseline', context=context, intents=intents)


def authorize(preview, now):
    return Authorization(purpose='execute_synthetic_workflow', run_id=preview.input.run_id,
        preview_sha256=input_hash(preview), authorization_id='manual-1', operator_id='synthetic-tester', authorized_at=now)


def prepare(tmp_path, signals, orders=None):
    broker = PaperBroker(tmp_path / 'broker.sqlite', strict=True)
    orders = orders or (proposal(),)
    for o in orders: staged(broker, signals[-1], o.proposal_id, o.ticker, o.side, o.quantity)
    store = WorkflowStore(tmp_path / 'workflow.sqlite')
    p = plan(broker, signals, orders)
    return broker, store, p


def test_preview_is_persisted_and_never_executes(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        before = b.execution_state()
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        assert preview.steps[0].status == 'PROPOSED'
        assert len(preview.steps) == 6
        assert b.execution_state() == before and not b.fills()
        assert store.load_preview(p.run_id) == preview
        assert replay_preview(preview, expected_sha256=input_hash(preview), trust=signals[3]) == preview
        assert 'PREVIEW ONLY' in human_preview(preview)
        with pytest.raises(ValueError, match='authorization'):
            execute_workflow(p.run_id, authorization=None, broker=b, store=store, trust=signals[3])


def test_authorization_exact_identity_buy_replay_and_report(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        auth = authorize(preview, signals[-1])
        with pytest.raises(ValueError, match='identity'):
            execute_workflow(p.run_id, authorization=auth.model_copy(update={'preview_sha256': '0' * 64}), broker=b, store=store, trust=signals[3])
        report = execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        assert report.steps[0].status == 'FILLED' and report.final_cash_eur == 9000
        assert report.final_metrics.invested == 1000
        assert execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3]) == report
        assert len(b.fills()) == 1
        assert store.load_report(expected_sha256=input_hash(report)) == report
        assert replay_workflow_report(report, expected_sha256=input_hash(report), preview=preview, trust=signals[3]) == report
        assert 'SYNTHETIC' in human_report(report) and 'FX=q1' in human_report(report)


@pytest.mark.parametrize('change', ['fx', 'price', 'snapshot', 'signals'])
def test_changed_inputs_conflict_with_preview_identity(tmp_path, signals, change):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        data = p.model_dump(mode='json')
        if change == 'fx': data['intents'][0]['fx']['source_quote']['rate'] = '.99'
        elif change == 'price': data['intents'][0]['order']['entry_price'] = '101'
        elif change == 'snapshot': data['context']['snapshot_id'] = 'changed'
        else: data['signals_sha256'] = '0' * 64
        with pytest.raises(ValueError):
            preview_workflow(WorkflowInput.model_validate(data), broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        assert not b.fills()


@pytest.mark.parametrize('failure', ['same_close', 'stale_fx', 'future_fx', 'unavailable_price', 'wrong_signal', 'wrong_side'])
def test_invalid_execution_inputs_are_rejected_without_fills(tmp_path, signals, failure):
    b, store, p = prepare(tmp_path, signals)
    with b:
        data = p.model_dump(mode='json')
        intent = data['intents'][0]
        if failure == 'same_close':
            intent['execution_at'] = signals[0].daily_inputs.decision_at.isoformat()
            intent['execution_price_at'] = intent['execution_at']
        elif failure == 'stale_fx': intent['fx']['source_quote']['effective_at'] = (signals[-1] - timedelta(seconds=61)).isoformat()
        elif failure == 'future_fx': intent['fx']['source_quote']['retrieved_at'] = (signals[-1] + timedelta(seconds=1)).isoformat()
        elif failure == 'unavailable_price': intent['price_available_at'] = (signals[-1] + timedelta(seconds=1)).isoformat()
        elif failure == 'wrong_signal': intent['signal_sha256'] = '0' * 64
        else: intent['order']['side'] = 'SELL'
        # Keep context consistent when testing signal-side checking.
        if failure == 'wrong_side': data['context']['proposal_usd']['side'] = 'SELL'
        preview = preview_workflow(WorkflowInput.model_validate(data), broker=b, store=store,
                                   preview_at=signals[-1], trust=signals[3])
        assert preview.steps[0].status == 'REJECTED'
        assert not b.fills()


def test_missing_fx_synthetic_trust_and_strict_separation(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        data = p.model_dump(mode='json')
        del data['intents'][0]['fx']
        with pytest.raises(ValueError): WorkflowInput.model_validate(data)
        with pytest.raises(ValueError): preview_workflow(p, broker=b, store=store, preview_at=signals[-1])
        data = p.model_dump(mode='json')
        data['signals']['scope'] = 'real'
        with pytest.raises(ValueError): WorkflowInput.model_validate(data)
        assert TrustRegistry().pins == ()
    with PaperBroker(tmp_path / 'legacy.sqlite') as legacy:
        with pytest.raises(ValueError, match='Strict'):
            preview_workflow(p, broker=legacy, store=store, preview_at=signals[-1], trust=signals[3])


@pytest.mark.parametrize('change', ['kill', 'state'])
def test_changed_portfolio_and_kill_are_rechecked(tmp_path, signals, change):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        if change == 'kill': b.set_kill_switch(True, timestamp=signals[-1], reason='manual test')
        else: b.create_order('external', 'MSFT', 'BUY', 1, timestamp=signals[-1])
        report = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert report.steps[0].status == 'REJECTED'
        assert 'STALE_STATE' in report.steps[0].reasons[0]
        assert not b.fills()


def test_sequence_can_fill_two_orders_without_adopting_external_state(tmp_path, signals):
    orders = (proposal(), proposal('m', 'MSFT'))
    b, store, p = prepare(tmp_path, signals, orders)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        report = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert [s.status for s in report.steps[:2]] == ['FILLED', 'FILLED']
        assert len(b.fills()) == 2 and report.final_cash_eur == 8000


def test_partial_completion_and_durable_gate_rejection(tmp_path, signals):
    orders = (proposal(), proposal('m', 'MSFT'))
    b, store, p = prepare(tmp_path, signals, orders)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        b._db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON fills WHEN NEW.order_id='m' BEGIN SELECT RAISE(ABORT,'synthetic second fill fault'); END")
        report = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert report.status == 'PARTIAL'
        assert [s.status for s in report.steps[:2]] == ['FILLED', 'REJECTED']
        assert len(b.fills()) == 1


def test_restart_recovers_gap_after_broker_commit(tmp_path, signals, monkeypatch):
    orders = (proposal(), proposal('m', 'MSFT'))
    b, store, p = prepare(tmp_path, signals, orders)
    preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
    auth = authorize(preview, signals[-1])
    original = store._step
    def interrupt(run_id, req, outcome=None):
        if outcome is not None: raise KeyboardInterrupt('simulated process interruption after broker commit')
        return original(run_id, req, outcome)
    monkeypatch.setattr(store, '_step', interrupt)
    with pytest.raises(KeyboardInterrupt): execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
    assert len(b.fills()) == 1
    b.close()
    restarted = WorkflowStore(tmp_path / 'workflow.sqlite')
    with PaperBroker(tmp_path / 'broker.sqlite') as b:
        report = execute_workflow(p.run_id, authorization=auth, broker=b, store=restarted, trust=signals[3])
        assert [s.status for s in report.steps[:2]] == ['FILLED', 'FILLED']
        assert len(b.fills()) == 2


def test_journal_sqlite_failure_and_invalid_reference(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        with sqlite3.connect(store.path) as db:
            db.execute("CREATE TRIGGER fail_prepare BEFORE INSERT ON steps BEGIN SELECT RAISE(ABORT,'journal failure'); END")
        auth = authorize(preview, signals[-1])
        report = execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        assert report.status == 'INTERRUPTED' and not b.fills()
        with sqlite3.connect(store.path) as db: db.execute('DROP TRIGGER fail_prepare')
        report = execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        changed = report.steps[0].model_copy(update={'order_id': 'wrong-order'})
        altered = report.model_copy(update={'steps': (changed, *report.steps[1:])})
        with pytest.raises(ValueError, match='reference'):
            replay_workflow_report(altered, expected_sha256=input_hash(altered), preview=preview, trust=signals[3])


def test_sell_and_risk_limit_rejection(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        # Existing flat synthetic JNJ data produces SELL; no holding means rejection.
        staged(b, signals[-1], 'sell', 'JNJ', 'SELL', 1)
        sell = plan(b, signals, (proposal('sell', 'JNJ', 'SELL', 1),), run='sell')
        preview = preview_workflow(sell, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        assert preview.steps[0].advisory_risk.decision == 'REJECTED'
        assert 'OVERSELL' in preview.steps[0].reasons[0]


def test_risk_limit_and_no_external_requests(tmp_path, signals, monkeypatch):
    import socket
    def forbidden(*args, **kwargs): raise AssertionError('External network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    b, store, p = prepare(tmp_path, signals, (proposal(qty=21),))
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        assert preview.steps[0].status == 'REJECTED'
        report = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert report.status == 'REJECTED' and not b.fills()


def test_successful_sell_uses_existing_signal_and_gate_policy(tmp_path, signals, fixture):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        calendar, observed, evidence, verified, decision = fixture
        root = registry(calendar, evidence)
        root = root.model_copy(update={'pins': (*root.pins, signals[3].pins[-1])})
        inputs = freeze_verified_daily_inputs(calendar, observed, evidence,
            policy=VerificationPolicy(publication_delay_seconds=600), verified_at=verified,
            decision_at=decision, trust=root)
        report = replay_verified_daily_signals(inputs, expected_sha256=input_hash(inputs), trust=root)
        sell_signals = (inputs, report, signals[2], root, signals[-1])
        staged(b, signals[-1], 'sell-a', 'AAPL', 'SELL', 5)
        sell_plan = plan(b, sell_signals, (proposal('sell-a', 'AAPL', 'SELL', 5),), run='sell-success')
        preview = preview_workflow(sell_plan, broker=b, store=store, preview_at=signals[-1], trust=root)
        result = execute_workflow(sell_plan.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=root)
        assert result.steps[0].status == 'FILLED'
        assert b.reconcile().positions[0].quantity == 5 and result.final_cash_eur == 9500


def test_hold_signal_cannot_be_promoted_into_trade(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        # BEAR-filtered variant holds while baseline buys; strategy is unchanged.
        selected = next(d for d in signals[1].daily_report.decisions if d.ticker == 'AAPL' and d.variant == 'bear_filtered')
        assert selected.decision == 'HOLD'
        changed = p.model_copy(update={'variant': 'bear_filtered',
            'intents': (p.intents[0].model_copy(update={'signal_sha256': input_hash(selected)}),)})
        preview = preview_workflow(changed, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        assert preview.steps[0].status == 'SKIPPED'
        report = execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=b, store=store, trust=signals[3])
        assert all(s.status == 'SKIPPED' for s in report.steps) and not b.fills()


def test_corrupted_broker_audit_stops_recovery_without_duplicate_fill(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b:
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        auth = authorize(preview, signals[-1])
        execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        b._db.execute('UPDATE gate_attempts SET record_sha256=?', ('0' * 64,))
        report = execute_workflow(p.run_id, authorization=auth, broker=b, store=store, trust=signals[3])
        assert report.status == 'INTERRUPTED' and report.steps[0].status == 'ERROR'
        assert len(b.fills()) == 1


def test_authorization_cannot_be_reused_on_identical_other_ledger(tmp_path, signals):
    b, store, p = prepare(tmp_path, signals)
    with b, PaperBroker(tmp_path / 'other.sqlite', strict=True) as other:
        staged(other, signals[-1])
        assert other.execution_state() == b.execution_state()
        preview = preview_workflow(p, broker=b, store=store, preview_at=signals[-1], trust=signals[3])
        with pytest.raises(ValueError, match='different strict ledger'):
            execute_workflow(p.run_id, authorization=authorize(preview, signals[-1]), broker=other, store=store, trust=signals[3])
        assert not other.fills() and not b.fills()
