"""Synthetic exception eligibility and strict-ledger safety regressions."""
from decimal import Decimal

import pytest

from tests.test_pretrade_risk import order, snapshot, holding, evaluate, config, codes, NOW
from tests.test_gated_execution import broker, accepted, request, rejected
from tools.pretrade_risk import Outstanding


@pytest.mark.parametrize('quantity', [1, 5, 10])
def test_full_partial_liquidation_can_retain_existing_violations(quantity):
    s = snapshot(cash='6000', holdings=(holding(), holding('MSFT',30)))
    d = evaluate(s, order(side='SELL', quantity=quantity))
    assert d.decision == 'APPROVED' and 'RISK_REDUCING_SELL_EXCEPTION' in codes(d)
    assert d.projected.invested < d.current.invested
    assert d.projected.planned_risk <= d.current.planned_risk
    assert next(p for p in d.projected.positions if p.ticker=='MSFT').concentration > Decimal('.2')


def test_pending_buy_cannot_use_sell_exception_to_expand_risk_or_exposure():
    s = snapshot(cash='6000', holdings=(holding(), holding('MSFT',30)), outstanding=(Outstanding(
        order=order(proposal_id='pending',ticker='JPM',quantity=20,stop_price='80'), status='ACCEPTED'),))
    d = evaluate(s, order(side='SELL', quantity=1))
    assert d.decision == 'REJECTED'
    assert {'POSITION_RISK','POSITION_EXPOSURE'} <= codes(d)
    assert d.projected.invested > d.current.invested and d.projected.planned_risk > d.current.planned_risk


def test_no_new_concentration_breach_created_by_exit_costs():
    # MSFT begins exactly at 20%. Costs lower equity, creating a NEW violation.
    s = snapshot(cash='7000', holdings=(holding(), holding('MSFT',20)))
    d = evaluate(s, order(side='SELL',quantity=10,commission='100'))
    assert d.current.positions[1].concentration == Decimal('.2')
    assert d.decision == 'REJECTED' and 'POSITION_EXPOSURE' in codes(d)


@pytest.mark.parametrize('failure', ['oversell','pending_oversell','negative_cash','reserve','duplicate'])
def test_exception_never_erases_protective_rejections(failure):
    s = snapshot(cash='6000', holdings=(holding(),holding('MSFT',30)))
    p = order(side='SELL',quantity=1)
    expected = ''
    if failure=='oversell': p=order(side='SELL',quantity=11); expected='OVERSELL'
    elif failure=='pending_oversell':
        pending=Outstanding(order=order(proposal_id='pending',ticker='MSFT',side='SELL',quantity=31),status='ACCEPTED')
        s=s.model_copy(update={'outstanding':(pending,)})
        expected='PENDING_OVERSELL'
    elif failure=='negative_cash': p=order(side='SELL',quantity=1,commission='10001'); expected='NEGATIVE_CASH'
    elif failure=='reserve': p=order(side='SELL',quantity=1,commission='6000'); expected='CASH_RESERVE'
    else: s=s.model_copy(update={'prior_proposal_ids':('new',)}); expected='DUPLICATE_PROPOSAL'
    result=evaluate(s,p)
    assert result.decision=='REJECTED' and expected in codes(result)


def test_buy_behavior_and_limits_stay_unchanged():
    s=snapshot(cash='6000',holdings=(holding(),holding('MSFT',30)))
    assert evaluate(s,order(ticker='JPM',quantity=1)).decision=='REJECTED'
    assert evaluate(p=order(quantity=20)).decision=='APPROVED'
    assert evaluate(p=order(quantity=21)).decision=='REJECTED'


def test_strict_exit_reduces_breached_position_and_reconciles(broker):
    accepted(broker)
    assert broker.execute_gated(request(broker)).status=='FILLED'
    accepted(broker,'exit',side='SELL',quantity=1)
    req=request(broker,'exit','reduce',proposal_changes={'entry_price':'90'})
    marks=tuple(m.model_copy(update={'price':Decimal(90)}) for m in req.risk_inputs.marks_usd)
    req=req.model_copy(update={'risk_inputs':req.risk_inputs.model_copy(update={'marks_usd':marks})})
    outcome=broker.execute_gated(req)
    assert outcome.status=='FILLED' and 'RISK_REDUCING_SELL_EXCEPTION' in codes(outcome.risk)
    assert broker.reconcile().positions[0].quantity==9
    assert broker.execution_attempt('reduce')==outcome
