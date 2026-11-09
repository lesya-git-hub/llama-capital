from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
from threading import Barrier

import pytest

from providers.paper_broker import PaperBroker
from tools.fx_conversion import (FXQuote, FXPolicy, USDProposal, USDHolding, USDMark,
                                 USDOutstanding, RiskConversionRequest, canonical_quote)
from tools.gated_execution import ExecutionOutcome, ExecutionRequest, replay_execution_checks
from tools.historical_snapshot import canonical_json, input_hash
from tools.pretrade_risk import RiskConfiguration


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def broker(tmp_path):
    with PaperBroker(tmp_path / 'strict.sqlite', strict=True) as value:
        yield value


def accepted(broker, identity='buy', ticker='AAPL', side='BUY', quantity=10):
    broker.create_order(identity, ticker, side, quantity, timestamp=NOW - timedelta(seconds=2))
    broker.accept_order(identity, timestamp=NOW - timedelta(seconds=1))


def usd(row, **changes):
    return USDProposal(**(dict(proposal_id=row['order_id'], ticker=row['ticker'], side=row['side'],
        quantity=row['quantity'], entry_price='100', stop_price='95', commission='0', slippage='0',
        exit_commission='0', exit_slippage='0') | changes))


def request(broker, identity='buy', attempt='attempt', proposal_changes=None, policy_changes=None):
    state = broker.execution_state()
    raw = json.loads(state.content)
    target = next(o for o in raw['orders'] if o['order_id'] == identity)
    holding_terms = {h['ticker']: json.loads(h['terms_json']) for h in raw.get('gate_holdings', ())}
    held = tuple(USDHolding(**(holding_terms[p['ticker']] | dict(quantity=p['quantity']))) for p in raw['positions'])
    frozen_orders = {o['order_id']: o['terms_json'] for o in raw.get('gate_order_terms', ())}
    pending = tuple(USDOutstanding(order=(USDProposal.model_validate_json(frozen_orders[o['order_id']])
        if o['order_id'] in frozen_orders else usd(o)), status=o['status']) for o in raw['orders']
        if o['status'] in ('CREATED', 'ACCEPTED') and o['order_id'] != identity)
    tickers = {p['ticker'] for p in raw['positions']} | {o.order.ticker for o in pending} | {target['ticker']}
    source = RiskConversionRequest(snapshot_id='SYNTHETIC-ONLY', source='fixture', as_of=NOW,
        cash_eur=raw['account'][0]['cash'], holdings_usd=held,
        marks_usd=tuple(USDMark(ticker=t, price='100', as_of=NOW) for t in sorted(tickers)),
        outstanding_usd=pending, proposal_usd=usd(target, **(proposal_changes or {})))
    quote = FXQuote(scope='synthetic_test', pair='USD_EUR', direction='EUR_PER_USD', rate='1',
        effective_at=NOW, retrieved_at=NOW, provider_id='SYNTHETIC', dataset_id='fixture', quote_id='fx-1',
        payload_sha256=sha256(b'fixture').hexdigest(), price_convention='indicative_mid', provenance='TEST ONLY')
    return ExecutionRequest(attempt_id=attempt, order_id=identity, expected_state_sha256=input_hash(state),
        execution_at=NOW, signal_available_at=NOW - timedelta(seconds=3), execution_price_at=NOW,
        risk_inputs=source, fx=canonical_quote(quote), fx_policy=FXPolicy(max_age_seconds=60),
        risk_policy=RiskConfiguration(**(dict(max_age_seconds=60) | (policy_changes or {}))))


def rejected(broker, req, text):
    before = broker.execution_state()
    result = broker.execute_gated(req)
    assert result.status == 'REJECTED'
    assert text in ' '.join(result.reasons)
    assert result.before == result.after == before
    assert broker.execution_state() == before
    assert broker.execution_attempt(req.attempt_id) == result
    return result


def test_success_buy_audit_reconstruction_and_exact_retry(broker):
    accepted(broker)
    req = request(broker)
    outcome = broker.execute_gated(req)
    assert outcome.status == 'FILLED'
    assert broker.portfolio().available_cash == 9000
    assert broker.reconcile().positions[0].quantity == 10
    assert outcome.risk.decision == 'APPROVED'
    assert outcome.converted.proposal.entry_price == Decimal(100)
    assert json.loads(outcome.fill_json)['reference_price'] == '1E+2'
    restored = ExecutionOutcome.model_validate_json(canonical_json(outcome))
    assert restored == outcome == broker.execution_attempt(req.attempt_id)
    assert replay_execution_checks(restored, expected_sha256=input_hash(outcome)) == outcome
    assert broker.execute_gated(req) == outcome
    assert len(broker.fills()) == 1


def test_strict_persists_and_cannot_downgrade_or_manually_fill(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
    with pytest.raises(ValueError, match='downgraded'): PaperBroker(path, strict=False)
    with PaperBroker(path) as b:
        assert b.strict
        with pytest.raises(ValueError, match='direct manual'): b.simulate_fill('buy', price=100, timestamp=NOW)
        with b._transaction():
            with pytest.raises(ValueError, match='authorization'):
                b._simulate_fill_locked('buy', Decimal(100), Decimal(0), Decimal(0), NOW.isoformat())
        assert b.get_order('buy').status == 'ACCEPTED'
        assert not b.fills()


def test_legacy_remains_unrestricted_and_not_silently_upgraded(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    with PaperBroker(path) as b:
        accepted(b, quantity=30)
        assert not b.strict
        b.simulate_fill('buy', price=100, timestamp=NOW)  # Legacy has no portfolio limits.
    with pytest.raises(ValueError, match='creating a new'): PaperBroker(path, strict=True)
    with PaperBroker(path, strict=False) as b:
        assert not b.strict and b.reconcile().positions[0].quantity == 30


def test_success_sell_and_unchanged_conservative_sell_policy(broker):
    accepted(broker, quantity=20)
    assert broker.execute_gated(request(broker)).status == 'FILLED'
    accepted(broker, 'sell', side='SELL', quantity=5)
    outcome = broker.execute_gated(request(broker, 'sell', 'sale'))
    assert outcome.status == 'FILLED'
    assert broker.reconcile().positions[0].quantity == 15
    accepted(broker, 'sell2', side='SELL', quantity=1)
    rejected(broker, request(broker, 'sell2', 'sale2', policy_changes={'max_position': '.1'}), 'POSITION_EXPOSURE')


@pytest.mark.parametrize('changes,policy,reason', [
    ({}, {}, 'POSITION_EXPOSURE'),
    ({'stop_price': '90'}, {'max_position': '.5'}, 'POSITION_RISK'),
    ({}, {'max_position': '.5', 'max_position_risk': '.5', 'min_cash': '.9'}, 'CASH_RESERVE'),
    ({}, {'max_position': '.5', 'max_position_risk': '.5', 'max_invested': '.1'}, 'TOTAL_EXPOSURE'),
])
def test_risk_limits_are_durable_rejections(broker, changes, policy, reason):
    accepted(broker, quantity=21)
    rejected(broker, request(broker, proposal_changes=changes, policy_changes=policy), reason)


def test_aggregate_risk_across_existing_holdings(broker):
    for i, ticker in enumerate(('MSFT', 'JPM', 'JNJ', 'XOM')):
        accepted(broker, str(i), ticker=ticker, quantity=20)
        assert broker.execute_gated(request(broker, str(i), f'a{i}')).status == 'FILLED'
    accepted(broker, 'new', ticker='WMT', quantity=1)
    rejected(broker, request(broker, 'new', 'aggregate', proposal_changes={'stop_price': '1'},
                             policy_changes={'max_invested': '1', 'min_cash': '0'}), 'AGGREGATE_RISK')


def test_insufficient_cash_and_holdings(broker):
    accepted(broker, quantity=101)
    rejected(broker, request(broker), 'NEGATIVE_CASH')
    broker.cancel_order('buy', timestamp=NOW)
    accepted(broker, 'sell', side='SELL', quantity=1)
    rejected(broker, request(broker, 'sell', 'sell-fail'), 'OVERSELL')


@pytest.mark.parametrize('failure', ['stale_fx', 'future_fx', 'unverified', 'lookahead', 'price_time', 'missing_marks'])
def test_fx_and_timing_integrity(broker, failure):
    accepted(broker)
    req = request(broker)
    data = req.model_dump(mode='json')
    expected = ''
    if failure == 'stale_fx':
        data['fx']['source_quote']['effective_at'] = (NOW - timedelta(seconds=61)).isoformat()
        expected = 'Stale'
    elif failure == 'future_fx':
        data['fx']['source_quote']['retrieved_at'] = (NOW + timedelta(seconds=1)).isoformat()
        expected = 'Future'
    elif failure == 'unverified':
        data['fx']['source_quote']['scope'] = 'unverified'
        expected = 'synthetic'
    elif failure == 'lookahead':
        data['signal_available_at'] = NOW.isoformat()
        expected = 'LOOKAHEAD'
    elif failure == 'price_time':
        data['execution_price_at'] = (NOW - timedelta(seconds=1)).isoformat()
        expected = 'PRICE_TIME'
    else:
        data['risk_inputs']['marks_usd'] = []
        expected = 'MISSING_VALUATION'
    rejected(broker, ExecutionRequest.model_validate(data), expected)


def test_missing_fx_invalid_price_and_naive_time_fail_before_mutation(broker):
    accepted(broker)
    req = request(broker)
    for change in ('fx', 'price', 'time', 'production'):
        data = req.model_dump(mode='json')
        if change == 'fx': data.pop('fx')
        elif change == 'price': data['risk_inputs']['proposal_usd']['entry_price'] = 'NaN'
        elif change == 'time': data['execution_at'] = '2026-11-09T12:00:00'
        else: data['mode'] = 'trusted_production'
        with pytest.raises(ValueError): ExecutionRequest.model_validate(data)
    assert not broker.fills()


def test_kill_switch_blocks_pending_but_exact_completed_retry_is_read_only(broker):
    accepted(broker)
    req = request(broker)
    filled = broker.execute_gated(req)
    accepted(broker, 'second', ticker='MSFT')
    broker.set_kill_switch(True, timestamp=NOW, reason='test kill')
    assert broker.execute_gated(req) == filled
    rejected(broker, request(broker, 'second', 'killed'), 'KILL_SWITCH')
    assert len(broker.fills()) == 1


def test_preliminary_approval_cannot_authorize_changed_state(broker):
    accepted(broker)
    req = request(broker)
    accepted(broker, 'other', ticker='MSFT')
    rejected(broker, req, 'STALE_STATE')


def test_pending_coverage_and_frozen_assumptions(broker):
    accepted(broker)
    accepted(broker, 'pending', ticker='MSFT')
    req = request(broker)
    bad = req.model_copy(update={'risk_inputs': req.risk_inputs.model_copy(update={'outstanding_usd': ()})})
    rejected(broker, bad, 'PENDING_COVERAGE')
    req = req.model_copy(update={'attempt_id': 'valid'})
    assert broker.execute_gated(req).status == 'FILLED'
    changed = request(broker, 'pending', 'changed', proposal_changes={'stop_price': '99'})
    rejected(broker, changed, 'TERMS_CONFLICT')


def test_stop_assumptions_cannot_silently_change(broker):
    accepted(broker)
    broker.execute_gated(request(broker))
    accepted(broker, 'sell', side='SELL', quantity=1)
    req = request(broker, 'sell', 'stop-change')
    changed = req.risk_inputs.holdings_usd[0].model_copy(update={'stop_price': Decimal(99)})
    req = req.model_copy(update={'risk_inputs': req.risk_inputs.model_copy(update={'holdings_usd': (changed,)})})
    rejected(broker, req, 'STOP_CONFLICT')


def test_conflicting_request_id_and_filled_order_cannot_execute_twice(broker):
    accepted(broker)
    req = request(broker)
    broker.execute_gated(req)
    with pytest.raises(ValueError, match='Conflicting'):
        broker.execute_gated(req.model_copy(update={'signal_available_at': NOW - timedelta(seconds=4)}))
    rejected(broker, request(broker, attempt='new-attempt'), 'ORDER_STATUS')
    assert len(broker.fills()) == 1


def test_fill_failure_rolls_back_finances_and_commits_only_rejection(broker):
    accepted(broker)
    req = request(broker)
    broker._db.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN SELECT RAISE(ABORT,'injected fill failure'); END")
    result = rejected(broker, req, 'injected fill failure')
    assert result.risk.decision == 'APPROVED'
    assert broker.reconcile().available_cash == 10000
    assert broker.get_order('buy').status == 'ACCEPTED'
    assert not broker.fills()


def test_evidence_failure_rolls_back_entire_success_and_recovers(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
        before = b.execution_state()
        b._db.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON gate_attempts BEGIN SELECT RAISE(ABORT,'injected evidence failure'); END")
        with pytest.raises(sqlite3.IntegrityError): b.execute_gated(req)
        assert b.execution_state() == before
        assert not b.fills()
        with pytest.raises(KeyError): b.execution_attempt(req.attempt_id)
        b._db.execute('DROP TRIGGER fail_evidence')
    with PaperBroker(path) as b:
        assert b.reconcile().available_cash == 10000
        result = b.execute_gated(req)
        assert result.status == 'FILLED'
    with PaperBroker(path) as b:
        assert b.execute_gated(req) == result
        with pytest.raises(ValueError, match='direct manual'):
            b.simulate_fill('buy', price=100, timestamp=NOW)
        assert len(b.fills()) == 1


def test_concurrent_identical_requests_execute_once(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b)
        req = request(b)
    barrier = Barrier(2)
    def run():
        with PaperBroker(path) as b:
            barrier.wait()
            return b.execute_gated(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    assert results[0] == results[1] and results[0].status == 'FILLED'
    with PaperBroker(path) as b:
        assert len(b.fills()) == 1


def test_concurrent_competitors_reject_old_state_and_never_overallocate(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b, 'a', quantity=10)
        accepted(b, 'b', quantity=10)
        requests = [request(b, i, i) for i in ('a', 'b')]
    barrier = Barrier(2)
    def run(req):
        with PaperBroker(path) as b:
            barrier.wait()
            return b.execute_gated(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, requests))
    assert sorted(r.status for r in results) == ['FILLED', 'REJECTED']
    assert 'STALE_STATE' in next(r for r in results if r.status == 'REJECTED').reasons[0]
    with PaperBroker(path) as b:
        assert b.reconcile().positions[0].quantity == 10
        loser = next(r.request.order_id for r in results if r.status == 'REJECTED')
        assert b.execute_gated(request(b, loser, 'resubmitted')).status == 'FILLED'
        assert b.reconcile().positions[0].quantity == 20


def test_pending_orders_cannot_collectively_bypass_risk(broker):
    accepted(broker, 'a', quantity=15)
    accepted(broker, 'b', quantity=15)
    rejected(broker, request(broker, 'a', 'a'), 'POSITION_EXPOSURE')
    rejected(broker, request(broker, 'b', 'b'), 'POSITION_EXPOSURE')
    assert not broker.fills()


def test_failure_after_fill_and_status_rolls_back_before_durable_rejection(broker):
    accepted(broker)
    req = request(broker)
    broker._db.execute("CREATE TRIGGER fail_after_fill BEFORE INSERT ON gate_holdings BEGIN SELECT RAISE(ABORT,'post-fill fault'); END")
    outcome = rejected(broker, req, 'post-fill fault')
    assert broker.get_order('buy').status == 'ACCEPTED'
    assert broker.reconcile().available_cash == 10000
    assert not broker.fills()
    assert replay_execution_checks(outcome, expected_sha256=input_hash(outcome)) == outcome


def test_rejection_restart_and_audit_tampering(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        accepted(b, quantity=21)
        req = request(b)
        outcome = rejected(b, req, 'POSITION_EXPOSURE')
    with PaperBroker(path) as b:
        assert b.execute_gated(req) == outcome
        assert b.reconcile().available_cash == 10000
        b._db.execute("UPDATE gate_attempts SET record_sha256=? WHERE attempt_id=?", ('0' * 64, req.attempt_id))
        with pytest.raises(ValueError, match='integrity'): b.execution_attempt(req.attempt_id)


def test_strict_schema_cannot_be_silently_reclassified_as_legacy(tmp_path):
    path = tmp_path / 'strict.sqlite'
    with PaperBroker(path, strict=True) as b:
        b._db.execute('PRAGMA user_version=1')  # Corruption, not an approved migration.
    with pytest.raises(ValueError, match='downgrade'): PaperBroker(path)


def test_fx_values_used_identically_for_risk_and_fill(broker):
    accepted(broker)
    req = request(broker, proposal_changes={'commission': '1', 'slippage': '.1'})
    data = req.model_dump(mode='json')
    data['fx']['source_quote']['rate'] = '.92'
    outcome = broker.execute_gated(ExecutionRequest.model_validate(data))
    assert outcome.status == 'FILLED'
    fill = broker.fills()[0]
    assert fill.reference_price == outcome.converted.proposal.entry_price == Decimal(92)
    assert fill.commission == outcome.converted.proposal.commission == Decimal('.92')
    assert fill.slippage_per_share == outcome.converted.proposal.slippage == Decimal('.092')
    assert broker.reconcile().available_cash == outcome.risk.projected.cash


def test_no_external_transport_is_used(broker, monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('External transport forbidden in synthetic execution')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    accepted(broker)
    assert broker.execute_gated(request(broker)).status == 'FILLED'
