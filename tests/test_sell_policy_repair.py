"""Synthetic exit regressions: repair stop eligibility without relaxing limits."""
from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.test_pretrade_risk import order, snapshot, config, evaluate, holding, codes, NOW
from tests.test_gated_execution import broker, accepted, request, rejected
from tools.fx_conversion import USDMark
from tools.pretrade_risk import Mark
from tools.operational_monitoring import monitor, MonitoringPolicy
from tools.operational_controls import activate_operational_block
from tools.historical_snapshot import input_hash
from providers.paper_broker import PaperBroker


@pytest.mark.parametrize('price', ['95', '90'])
def test_full_sell_accepts_stop_at_or_above_mark(price):
    s = snapshot(cash='9000', holdings=(holding(),), marks=(Mark(ticker='AAPL', price=price, as_of=NOW),))
    decision = evaluate(s, order(side='SELL', quantity=10, entry_price=price, stop_price='95'))
    assert decision.decision == 'APPROVED'
    assert decision.projected.invested == decision.projected.planned_risk == 0
    assert decision.current.planned_risk == 10 * Decimal(price)  # No breached-stop protective credit.


def test_partial_exit_retains_conservative_breached_stop_risk():
    s = snapshot(cash='9800', holdings=(holding(quantity=2),), marks=(Mark(ticker='AAPL', price='90', as_of=NOW),))
    result = evaluate(s, order(side='SELL', quantity=1, entry_price='90'))
    assert result.decision == 'APPROVED'
    assert result.projected.planned_risk == 90 and result.projected.positions[0].quantity == 1
    too_large = s.model_copy(update={'holdings': (holding(quantity=10),), 'cash': Decimal(9000)})
    reduced = evaluate(too_large, order(side='SELL', quantity=1, entry_price='90'))
    assert reduced.decision == 'APPROVED' and 'RISK_REDUCING_SELL_EXCEPTION' in codes(reduced)
    assert reduced.projected.planned_risk < reduced.current.planned_risk


@pytest.mark.parametrize('change', [{'stop_price':'0'}, {'exit_slippage':'95'}, {'quantity':0}, {'quantity':True}, {'slippage':'90'}])
def test_sell_still_rejects_invalid_structure_and_adverse_prices(change):
    with pytest.raises(ValueError):
        order(**(dict(side='SELL', entry_price='90') | change))


def test_buy_stop_and_remaining_portfolio_limits_stay_strict():
    with pytest.raises(ValueError):
        order(entry_price='90', stop_price='95')
    breached = snapshot(holdings=(holding(),), marks=(Mark(ticker='AAPL', price='90', as_of=NOW),))
    assert 'INVALID_STOP' in codes(evaluate(breached, order(entry_price='90', stop_price='85')))
    s = snapshot(cash='6000', holdings=(holding(), holding('MSFT',30)))
    decision = evaluate(s, order(side='SELL', quantity=10))
    assert decision.decision == 'APPROVED' and 'RISK_REDUCING_SELL_EXCEPTION' in codes(decision)
    assert decision.projected.invested < decision.current.invested


def test_oversell_pending_reservations_stale_and_costs_still_reject():
    s = snapshot(cash='9000', holdings=(holding(),))
    assert 'OVERSELL' in codes(evaluate(s, order(side='SELL', quantity=11)))
    stale = s.model_copy(update={'as_of': NOW-timedelta(seconds=61)})
    assert 'STALE_VALUATION' in codes(evaluate(stale, order(side='SELL')))
    assert 'NEGATIVE_CASH' in codes(evaluate(s, order(side='SELL', commission='10001')))


def exit_request(broker, quantity=10):
    accepted(broker, 'exit', side='SELL', quantity=quantity)
    req = request(broker, 'exit', 'exit-attempt', proposal_changes={'entry_price':'90'})
    marks = tuple(USDMark(ticker=m.ticker, price='90', as_of=NOW) for m in req.risk_inputs.marks_usd)
    return req.model_copy(update={'risk_inputs': req.risk_inputs.model_copy(update={'marks_usd': marks})})


@pytest.mark.parametrize('quantity,sell', [(10,10),(2,1)])
def test_strict_full_partial_exit_audit_replay_and_no_short(broker, quantity, sell):
    accepted(broker, quantity=quantity)
    assert broker.execute_gated(request(broker)).status == 'FILLED'
    outcome = broker.execute_gated(exit_request(broker, sell))
    assert outcome.status == 'FILLED' and broker.execution_attempt('exit-attempt') == outcome
    portfolio = broker.reconcile()
    assert sum(h.quantity for h in portfolio.positions) == quantity-sell
    assert portfolio.realized_pnl == -10*sell
    assert len(broker.fills()) == 2


@pytest.mark.parametrize('failure', ['kill','stale_fx','stale_state','oversell','latch'])
def test_strict_exit_safety_guards_remain_durable(broker, failure):
    accepted(broker)
    broker.execute_gated(request(broker))
    if failure == 'kill':
        # Stage while enabled; capture the new killed state into the request.
        req = exit_request(broker)
        broker.set_kill_switch(True, timestamp=NOW, reason='Synthetic exit-control test')
        req = req.model_copy(update={'expected_state_sha256':input_hash(broker.execution_state())})
        expected = 'KILL_SWITCH'
    elif failure == 'latch':
        req = exit_request(broker)
        path = broker._db.execute('PRAGMA database_list').fetchone()[2]
        report = monitor(path, report_id='wrong-opening', reported_at=NOW,
            policy=MonitoringPolicy(expected_opening_cash='9999'))
        assert report.status == 'CRITICAL'
        activate_operational_block(path, report, expected_sha256=input_hash(report), activation_id='test-latch',
            operator_id='test-operator', reason='Synthetic declared-capital finding', timestamp=NOW)
        req = req.model_copy(update={'expected_state_sha256':input_hash(broker.execution_state())})
        expected = 'OPERATIONAL_BLOCK'
    else:
        req = exit_request(broker, 11 if failure=='oversell' else 10)
        expected = {'stale_state':'STALE_STATE','oversell':'OVERSELL','stale_fx':'Stale FX'}[failure]
        if failure=='stale_state':
            req = req.model_copy(update={'expected_state_sha256':'0'*64})
        elif failure=='stale_fx':
            quote = req.fx.source_quote.model_copy(update={'effective_at': NOW-timedelta(seconds=61)})
            req = req.model_copy(update={'fx':req.fx.model_copy(update={'source_quote':quote})})
    outcome = rejected(broker, req, expected)
    assert len(broker.fills()) == 1 and len(broker.reconcile().positions) == 1


@pytest.mark.parametrize('owned', [2,10])
def test_competing_partial_exits_preserve_locked_state_and_holdings(broker, owned):
    accepted(broker, quantity=owned)
    broker.execute_gated(request(broker))
    accepted(broker, 'exit-a', side='SELL', quantity=1)
    accepted(broker, 'exit-b', side='SELL', quantity=1)
    requests = []
    for identity in ('exit-a', 'exit-b'):
        req = request(broker, identity, identity, proposal_changes={'entry_price':'90'})
        marks = tuple(USDMark(ticker=m.ticker, price='90', as_of=NOW) for m in req.risk_inputs.marks_usd)
        requests.append(req.model_copy(update={'risk_inputs':req.risk_inputs.model_copy(update={'marks_usd':marks})}))
    path = broker._db.execute('PRAGMA database_list').fetchone()[2]
    barrier = Barrier(2)
    def compete(req):
        with PaperBroker(path, strict=True) as other:
            barrier.wait(timeout=10)
            return other.execute_gated(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, requests))
    assert sorted(o.status for o in outcomes) == ['FILLED','REJECTED']
    assert 'STALE_STATE' in next(o for o in outcomes if o.status=='REJECTED').reasons[0]
    assert broker.reconcile().positions[0].quantity == owned-1 and len(broker.fills()) == 2
    if owned == 10:
        assert 'RISK_REDUCING_SELL_EXCEPTION' in codes(next(o for o in outcomes if o.status=='FILLED').risk)
