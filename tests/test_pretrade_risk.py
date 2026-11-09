from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from tools.historical_snapshot import canonical_json, input_hash
from tools.pretrade_risk import (
    Holding, Mark, Outstanding, Proposal, RiskConfiguration, RiskDecision,
    ValuationSnapshot, evaluate_pretrade, size_pretrade_buy,
)


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def order(**changes):
    values = dict(proposal_id='new', ticker='AAPL', side='BUY', quantity=10,
                  entry_price='100', stop_price='95', commission='0', slippage='0',
                  exit_commission='0', exit_slippage='0', currency='EUR')
    return Proposal(**(values | changes))


def snapshot(**changes):
    values = dict(snapshot_id='synthetic-1', source='SYNTHETIC-ONLY', as_of=NOW,
                  currency='EUR', cash='10000', marks=tuple(
                      Mark(ticker=t, price='100', as_of=NOW) for t in ('AAPL', 'MSFT', 'JPM', 'JNJ', 'XOM', 'WMT')))
    return ValuationSnapshot(**(values | changes))


def config(**changes):
    return RiskConfiguration(**(dict(max_age_seconds=60) | changes))


def evaluate(s=None, p=None, c=None):
    return evaluate_pretrade(s or snapshot(), p or order(), c or config(), evaluated_at=NOW)


def codes(decision):
    return {r.split(':')[0] for r in decision.reasons}


def holding(ticker='AAPL', quantity=10, **changes):
    return Holding(**(dict(ticker=ticker, quantity=quantity, stop_price='95',
                           exit_commission='0', exit_slippage='0') | changes))


def test_defaults_and_exact_position_boundary():
    c = config()
    assert (c.starting_capital, c.max_position, c.max_invested, c.min_cash,
            c.max_position_risk, c.max_aggregate_risk) == tuple(map(Decimal, ('10000', '.2', '.8', '.2', '.01', '.04')))
    assert evaluate(p=order(quantity=20)).decision == 'APPROVED'
    rejected = evaluate(p=order(quantity=21))
    assert {'POSITION_EXPOSURE', 'POSITION_RISK'} <= codes(rejected)


def test_mark_to_market_not_entry_cost():
    s = snapshot(cash='9000', holdings=(holding(),))
    d = evaluate(s)
    assert d.current.equity == 10000
    assert d.current.invested == 1000
    assert d.projected.invested == 2000
    assert d.projected.positions[0].concentration == Decimal('.2')


def test_total_exposure_and_cash_reserve_separately():
    s = snapshot(cash='2000', holdings=tuple(holding(t, 20) for t in ('MSFT', 'JPM', 'JNJ', 'XOM')))
    d = evaluate(s, order(quantity=1), config(max_position_risk='.1', max_aggregate_risk='.5'))
    assert {'TOTAL_EXPOSURE', 'CASH_RESERVE'} <= codes(d)
    assert 'CASH_RESERVE' in codes(evaluate(p=order(quantity=20), c=config(min_cash='.9')))


def test_aggregate_and_per_position_stop_risk():
    s = snapshot(cash='2000', holdings=tuple(holding(t, 20) for t in ('MSFT', 'JPM', 'JNJ', 'XOM')))
    d = evaluate(s, order(quantity=1), config(max_invested=1, min_cash=0))
    assert 'AGGREGATE_RISK' in codes(d)
    assert 'POSITION_RISK' in codes(evaluate(p=order(quantity=10, stop_price='89')))


def test_costs_slippage_and_negative_cash():
    d = evaluate(p=order(quantity=10, commission='2', slippage='1', exit_commission='3', exit_slippage='.5'))
    assert d.projected.cash == 8988
    assert d.projected.planned_risk == 70  # 10*(101-95+.5) + 2 + 3
    assert d.projected.equity == 9988
    assert 'NEGATIVE_CASH' in codes(evaluate(p=order(quantity=101)))


def test_sell_and_oversell_and_pending_share_reservation():
    s = snapshot(cash='9000', holdings=(holding(),))
    d = evaluate(s, order(side='SELL', quantity=5, commission='2', slippage='1'))
    assert d.decision == 'APPROVED'
    assert d.projected.cash == 9493
    assert d.projected.planned_risk == 25
    assert 'OVERSELL' in codes(evaluate(s, order(side='SELL', quantity=11)))
    pending = Outstanding(order=order(proposal_id='pending', side='SELL', quantity=6), status='ACCEPTED')
    s = s.model_copy(update={'outstanding': (pending,)})
    assert 'OVERSELL' in codes(evaluate(s, order(side='SELL', quantity=5)))


@pytest.mark.parametrize('status', ['CREATED', 'ACCEPTED'])
def test_pending_buys_cannot_bypass_limits(status):
    pending = Outstanding(order=order(proposal_id='pending', quantity=15), status=status)
    d = evaluate(snapshot(outstanding=(pending,)), order(quantity=10))
    assert 'POSITION_EXPOSURE' in codes(d)
    assert d.projected.cash == 7500


def test_pending_sells_do_not_fund_buys_or_release_capacity():
    s = snapshot(cash='8000', holdings=(holding(quantity=20),), outstanding=(
        Outstanding(order=order(proposal_id='pending', side='SELL', quantity=20), status='ACCEPTED'),))
    assert 'POSITION_EXPOSURE' in codes(evaluate(s, order(quantity=1)))
    s = snapshot(outstanding=(Outstanding(order=order(proposal_id='pending', side='SELL'), status='CREATED'),))
    assert 'PENDING_OVERSELL' in codes(evaluate(s))


def test_sell_does_not_remove_pending_buy_risk():
    pending = Outstanding(order=order(proposal_id='pending', quantity=10), status='ACCEPTED')
    s = snapshot(cash='9000', holdings=(holding(),), outstanding=(pending,))
    d = evaluate(s, order(side='SELL', quantity=10))
    assert d.projected.planned_risk == 50
    assert d.projected.positions[0].quantity == 10


def test_partial_sale_retains_full_remaining_exit_fee():
    s = snapshot(cash='9000', holdings=(holding(exit_commission='10'),))
    d = evaluate(s, order(side='SELL', quantity=5))
    assert d.projected.planned_risk == 35


def test_pending_sell_net_cost_is_reserved_without_proceeds_credit():
    s = snapshot(cash='9000', holdings=(holding(),), outstanding=(Outstanding(
        order=order(proposal_id='pending', side='SELL', quantity=1, commission='101'), status='ACCEPTED'),))
    d = evaluate(s, order(ticker='MSFT', quantity=1))
    assert d.projected.cash == 8899


def test_decimal_precision_limit_and_snapshot_order_identity():
    with pytest.raises(ValueError): order(commission='.0000000000001')
    s = snapshot(holdings=(holding('AAPL'), holding('MSFT')), cash='8000')
    reversed_s = s.model_copy(update={'holdings': s.holdings[::-1], 'marks': s.marks[::-1]})
    assert evaluate(s) == evaluate(reversed_s)
    assert input_hash(config()) == input_hash(config(max_position='.200'))


def test_nonpositive_equity_never_produces_approval_or_invented_ratios():
    d = evaluate(snapshot(cash='0'))
    assert d.decision == 'REJECTED'
    assert 'NONPOSITIVE_EQUITY' in codes(d)
    assert d.current.invested_fraction is None


def test_duplicate_ids_from_history_and_outstanding():
    assert 'DUPLICATE_PROPOSAL' in codes(evaluate(snapshot(prior_proposal_ids=('new',))))
    assert 'DUPLICATE_PROPOSAL' in codes(evaluate(snapshot(outstanding=(Outstanding(order=order(), status='CREATED'),))))
    # Equal economics under a different ID are a distinct intentional proposal.
    assert input_hash(order()) != input_hash(order(proposal_id='other'))


@pytest.mark.parametrize('field', ['snapshot', 'order', 'pending'])
def test_currency_boundary(field):
    s, p = snapshot(), order()
    if field == 'snapshot': s = snapshot(currency='USD')
    if field == 'order': p = order(currency='USD')
    if field == 'pending':
        s = snapshot(outstanding=(Outstanding(order=order(proposal_id='pending', currency='USD'), status='ACCEPTED'),))
    assert 'CURRENCY_MISMATCH' in codes(evaluate(s, p))


@pytest.mark.parametrize('age', [-1, 61])
def test_future_and_stale_marks(age):
    m = Mark(ticker='AAPL', price='100', as_of=NOW - timedelta(seconds=age))
    assert 'STALE_VALUATION' in codes(evaluate(snapshot(marks=(m,))))


def test_missing_marks_and_snapshot_causality():
    assert 'MISSING_VALUATION' in codes(evaluate(snapshot(marks=())))
    assert 'STALE_VALUATION' in codes(evaluate(snapshot(as_of=NOW - timedelta(seconds=61))))
    assert 'VALUATION_CAUSALITY' in codes(evaluate(snapshot(as_of=NOW - timedelta(seconds=1))))


@pytest.mark.parametrize('changes', [dict(entry_price='NaN'), dict(commission='Infinity'),
    dict(quantity=True), dict(quantity=-1), dict(quantity=1.5), dict(stop_price=None),
    dict(stop_price='101'), dict(slippage='-1'), dict(commission=True),
    dict(side='SHORT'), dict(stop_price='0'), dict(proposal_id=' ')])
def test_invalid_proposals(changes):
    with pytest.raises(ValueError): order(**changes)


def test_invalid_snapshot_configuration_and_revalidation():
    with pytest.raises(ValueError): snapshot(cash='-1')
    with pytest.raises(ValueError): holding(quantity=-1)
    with pytest.raises(ValueError): config(max_position='NaN')
    with pytest.raises(ValueError): config(max_age_seconds=True)
    with pytest.raises(ValueError): snapshot(holdings=(holding(), holding()))
    with pytest.raises(ValueError): evaluate(p=order().model_copy(update={'quantity': -1}))
    with pytest.raises(ValueError):
        evaluate_pretrade(snapshot(), order(), config(), evaluated_at=datetime(2026, 11, 9))


def test_position_sizing_with_explicit_stop_and_costs():
    qty, decision = size_pretrade_buy(snapshot(), order(quantity=100), config(), evaluated_at=NOW)
    assert qty == 20 and decision.decision == 'APPROVED'
    qty, _ = size_pretrade_buy(snapshot(), order(quantity=100, commission='1'), config(), evaluated_at=NOW)
    assert qty == 19
    qty, d = size_pretrade_buy(snapshot(cash='10'), order(quantity=100), config(), evaluated_at=NOW)
    assert qty == 0 and d.decision == 'REJECTED'
    with pytest.raises(ValueError):
        size_pretrade_buy(snapshot(), order(side='SELL'), config(), evaluated_at=NOW)


def test_deterministic_audit_context_and_no_mutation(tmp_path):
    s, p, c = snapshot(), order(commission='1.0'), config()
    original = canonical_json(s)
    a = evaluate(s, p, c)
    with localcontext() as ctx:
        ctx.prec = 4
        b = evaluate(ValuationSnapshot.model_validate_json(original), p, c)
    assert canonical_json(a) == canonical_json(b)
    assert RiskDecision.model_validate_json(canonical_json(a)) == a
    assert a.snapshot_sha256 == input_hash(s)
    assert canonical_json(s) == original
    assert list(tmp_path.iterdir()) == []
    assert evaluate(snapshot(), order(quantity=100)).decision == 'REJECTED'
    assert input_hash(order(commission='1')) == input_hash(order(commission='1.0'))
