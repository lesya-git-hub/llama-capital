from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, ROUND_FLOOR, localcontext
import sqlite3

import pytest

from providers.paper_broker import PaperBroker
from tools.backtesting import calculate_trade_result


D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds=0):
    return START + timedelta(seconds=seconds)


@pytest.fixture
def broker(tmp_path):
    with PaperBroker(tmp_path / 'paper.sqlite') as value:
        yield value


def accepted(broker, order_id, side='BUY', quantity=10, ticker='AAA', second=0):
    broker.create_order(order_id, ticker, side, quantity, timestamp=at(second))
    return broker.accept_order(order_id, timestamp=at(second + 1))


def fill(broker, order_id, price=100, second=2, **kwargs):
    return broker.simulate_fill(order_id, price=price, timestamp=at(second), **kwargs)


def test_default_capital_and_no_automatic_execution(broker):
    assert broker.portfolio().currency == 'EUR'
    assert broker.portfolio().available_cash == D('10000')
    order = broker.create_order('b', 'AAA', 'BUY', 10, timestamp=at())
    assert order.status == 'CREATED'
    assert broker.accept_order('b', timestamp=at(1)).status == 'ACCEPTED'
    assert broker.portfolio().available_cash == D('10000')
    assert broker.portfolio().positions == ()
    assert broker.fills() == ()


def test_buy_and_sell_include_explicit_costs(broker):
    accepted(broker, 'buy')
    buy = fill(broker, 'buy', commission='2', slippage_per_share='0.5')
    assert buy.execution_price == D('100.5')
    assert buy.cash_delta == D('-1007')
    state = broker.portfolio()
    assert state.available_cash == D('8993')
    assert state.positions[0].average_entry_cost == D('100.7')
    accepted(broker, 'sell', 'SELL', second=3)
    sell = fill(broker, 'sell', price=110, second=5, commission=3, slippage_per_share=1)
    assert sell.execution_price == 109
    assert sell.allocated_cost_basis == 1007
    assert sell.realized_pnl == 80
    assert broker.portfolio().available_cash == 10080
    assert broker.portfolio().realized_pnl == 80
    assert broker.portfolio().positions == ()
    assert [e.event for e in broker.audit_events()] == ['CREATED', 'ACCEPTED', 'FILLED'] * 2


def test_multiple_buys_weighted_average_and_partial_sales(broker):
    accepted(broker, 'b1', quantity=3)
    fill(broker, 'b1', price=10, commission=1)
    accepted(broker, 'b2', quantity=7, second=3)
    fill(broker, 'b2', price=20, second=5, commission=2)
    p = broker.portfolio().positions[0]
    assert p.quantity == 10
    assert p.cost_basis == 173
    assert p.average_entry_cost == D('17.3')
    accepted(broker, 's1', 'SELL', quantity=4, second=6)
    partial = fill(broker, 's1', price=25, second=8, commission=1)
    assert partial.allocated_cost_basis == D('69.2')
    assert partial.realized_pnl == D('29.8')
    p = broker.portfolio().positions[0]
    assert p.quantity == 6
    assert p.cost_basis == D('103.8')
    assert p.average_entry_cost == D('17.3')
    accepted(broker, 's2', 'SELL', quantity=6, second=9)
    fill(broker, 's2', price=15, second=11)
    state = broker.portfolio()
    assert state.positions == ()
    assert state.realized_pnl == 16
    assert state.available_cash == 10016


def test_partial_basis_rounding_assigns_residual_on_final_sale(broker):
    accepted(broker, 'b', quantity=3)
    fill(broker, 'b', price=1, commission=1)
    for i in range(3):
        accepted(broker, f's{i}', 'SELL', quantity=1, second=3 + i * 3)
        fill(broker, f's{i}', price=2, second=5 + i * 3)
    assert sum(f.allocated_cost_basis for f in broker.fills()) == 4
    assert broker.portfolio().realized_pnl == 2
    assert broker.portfolio().available_cash == 10002


@pytest.mark.parametrize('side,quantity,price,message', [
    ('BUY', 101, 100, 'Insufficient cash'), ('SELL', 1, 100, 'Insufficient holdings'),
])
def test_fill_failure_preserves_state_and_is_audited(broker, side, quantity, price, message):
    accepted(broker, 'order', side, quantity)
    before = broker.portfolio()
    with pytest.raises(ValueError, match=message):
        fill(broker, 'order', price)
    assert broker.portfolio() == before
    assert broker.get_order('order').status == 'ACCEPTED'
    assert broker.fills() == ()
    assert broker.audit_events()[-1].event == 'FILL_BLOCKED'


def test_costs_are_checked_before_buy_and_failed_fill_can_retry(broker):
    accepted(broker, 'b', quantity=100)
    with pytest.raises(ValueError, match='Insufficient cash'):
        fill(broker, 'b', commission=1)
    fill(broker, 'b', price=99, second=3, commission=1)
    assert broker.portfolio().available_cash == 99


def test_overselling_after_partial_sale_does_not_change_state(broker):
    accepted(broker, 'b')
    fill(broker, 'b')
    accepted(broker, 's1', 'SELL', quantity=6, second=3)
    accepted(broker, 's2', 'SELL', quantity=6, second=3)
    fill(broker, 's1', second=5)
    before = broker.portfolio()
    with pytest.raises(ValueError, match='Insufficient holdings'):
        fill(broker, 's2', second=6)
    assert broker.portfolio() == before


def test_order_and_fill_idempotency_and_conflict_detection(broker):
    order = accepted(broker, 'b')
    count = len(broker.audit_events())
    assert broker.create_order('b', 'AAA', 'BUY', 10, timestamp=at(10)) == order
    assert broker.accept_order('b', timestamp=at(10)) == order
    assert len(broker.audit_events()) == count
    a = fill(broker, 'b', commission=1)
    state = broker.portfolio()
    count = len(broker.audit_events())
    assert fill(broker, 'b', commission=1) == a
    assert broker.portfolio() == state
    assert len(broker.audit_events()) == count
    with pytest.raises(ValueError, match='conflicts'):
        broker.create_order('b', 'AAA', 'BUY', 11, timestamp=at())
    for changes in ({'price': 101}, {'commission': 2}, {'slippage_per_share': 1}, {'second': 4}):
        args = dict(price=100, commission=1, second=2)
        args.update(changes)
        with pytest.raises(ValueError, match='Conflicting fill retry'):
            fill(broker, 'b', **args)


def test_cancel_reject_and_invalid_transitions(broker):
    broker.create_order('c', 'AAA', 'BUY', 1, timestamp=at())
    assert broker.cancel_order('c', timestamp=at(1)).status == 'CANCELLED'
    assert broker.cancel_order('c', timestamp=at(2)).status == 'CANCELLED'
    accepted(broker, 'a')
    assert broker.cancel_order('a', timestamp=at(2)).status == 'CANCELLED'
    broker.create_order('r', 'AAA', 'BUY', 1, timestamp=at())
    assert broker.reject_order('r', timestamp=at(1), reason='Explicit test rejection').status == 'REJECTED'
    for order_id in ('c', 'a', 'r'):
        with pytest.raises(ValueError):
            broker.accept_order(order_id, timestamp=at(3))
        with pytest.raises(ValueError):
            fill(broker, order_id, second=3)
    accepted(broker, 'f')
    fill(broker, 'f')
    with pytest.raises(ValueError):
        broker.cancel_order('f', timestamp=at(3))
    with pytest.raises(ValueError):
        broker.reject_order('f', timestamp=at(3), reason='Too late')
    with pytest.raises(ValueError):
        broker.reject_order('f', timestamp=at(3), reason='')


def test_restart_reconstructs_state_orders_fills_and_audit(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path, initial_cash=2000) as broker:
        accepted(broker, 'b')
        fill(broker, 'b', price=100, commission=2)
        accepted(broker, 's', 'SELL', quantity=3, second=3)
        fill(broker, 's', price=120, second=5, commission=1)
        accepted(broker, 'pending', second=6)
        broker.set_kill_switch(True, timestamp=at(8), reason='Pause')
        state, fills, events = broker.portfolio(), broker.fills(), broker.audit_events()
    with PaperBroker(path) as broker:
        assert broker.portfolio() == state
        assert broker.fills() == fills
        assert broker.audit_events() == events
        assert broker.get_order('pending').status == 'ACCEPTED'
        assert fill(broker, 's', price=120, second=5, commission=1) == fills[-1]
    with pytest.raises(ValueError, match='will not be reset'):
        PaperBroker(path, initial_cash=3000)


def test_transaction_rollback_after_cash_and_position_update(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path) as broker:
        accepted(broker, 'b')
        before = broker.portfolio()
        events = broker.audit_events()
        with sqlite3.connect(path) as db:
            db.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
            fill(broker, 'b')
        assert broker.portfolio() == before
        assert broker.audit_events() == events
        assert broker.get_order('b').status == 'ACCEPTED'
        assert broker.fills() == ()
        with sqlite3.connect(path) as db:
            db.execute('DROP TRIGGER fail_fill')
        fill(broker, 'b')
        assert broker.get_order('b').status == 'FILLED'
    with PaperBroker(path) as broker:
        assert len(broker.fills()) == 1
        assert broker.portfolio().positions[0].quantity == 10


def test_kill_switch_blocks_orders_acceptance_and_fills_but_allows_cancel(broker):
    accepted(broker, 'pending')
    broker.create_order('created', 'AAA', 'BUY', 1, timestamp=at())
    broker.set_kill_switch(True, timestamp=at(2), reason='Emergency')
    before = broker.portfolio()
    with pytest.raises(ValueError, match='Kill switch'):
        fill(broker, 'pending', second=3)
    assert broker.portfolio() == before
    assert broker.create_order('new', 'AAA', 'BUY', 1, timestamp=at(3)).status == 'REJECTED'
    assert broker.accept_order('created', timestamp=at(3)).status == 'REJECTED'
    assert broker.cancel_order('pending', timestamp=at(4)).status == 'CANCELLED'
    broker.set_kill_switch(False, timestamp=at(5), reason='Manual resume')
    accepted(broker, 'resumed', second=6)
    fill(broker, 'resumed', second=8)
    assert broker.portfolio().positions[0].quantity == 10


def test_no_reservation_competing_buy_fills_are_serialized(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path, initial_cash=1000) as broker:
        accepted(broker, 'b1', quantity=8)
        accepted(broker, 'b2', quantity=8)

    def worker(order_id):
        with PaperBroker(path) as broker:
            try:
                fill(broker, order_id)
                return 'FILLED'
            except ValueError as exc:
                assert 'Insufficient cash' in str(exc)
                return 'BLOCKED'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, ('b1', 'b2'))) == ['BLOCKED', 'FILLED']
    with PaperBroker(path) as broker:
        assert broker.portfolio().available_cash == 200
        assert broker.portfolio().positions[0].quantity == 8
        assert len(broker.fills()) == 1


def test_round_trip_matches_v1_trade_cost_conventions(broker):
    reference = calculate_trade_result(100, 110, 10, fee_rate=0.001, slippage_rate=0.001)
    accepted(broker, 'b')
    fill(broker, 'b', commission='1.001', slippage_per_share='0.1')
    accepted(broker, 's', 'SELL', second=3)
    fill(broker, 's', price=110, second=5, commission='1.0989', slippage_per_share='0.11')
    assert float(broker.portfolio().realized_pnl) == pytest.approx(reference.net_pnl)


def test_multiticker_ledger_reconciliation_and_context_independence(broker):
    with localcontext() as ctx:
        ctx.prec = 4  # Broker arithmetic must not inherit caller rounding.
        accepted(broker, 'a', quantity=3)
        fill(broker, 'a', price='12.123456789012', commission='0.123456789012')
        accepted(broker, 'b', quantity=7, ticker='BBB', second=3)
        fill(broker, 'b', price='20.3456', second=5, commission='0.3')
        accepted(broker, 's', 'SELL', quantity=1, second=6)
        fill(broker, 's', price=30, second=8, commission='0.1')
    state = broker.portfolio()
    assert broker.reconcile() == state
    fills = broker.fills()
    assert state.available_cash == state.initial_cash + sum(f.cash_delta for f in fills)
    assert state.realized_pnl == sum(f.realized_pnl for f in fills)
    assert state.available_cash + sum(p.cost_basis for p in state.positions) == state.initial_cash + state.realized_pnl
    for position in state.positions:
        net_quantity = sum(f.quantity if f.side == 'BUY' else -f.quantity for f in fills if f.ticker == position.ticker)
        assert position.quantity == net_quantity


@pytest.mark.parametrize('value', [-1, 0, True, float('nan'), float('inf'), 'bad', '0.0000000000001'])
def test_invalid_price_does_not_touch_ledger(broker, value):
    accepted(broker, 'b')
    events = broker.audit_events()
    with pytest.raises(ValueError):
        fill(broker, 'b', price=value)
    assert broker.audit_events() == events
    assert broker.fills() == ()


@pytest.mark.parametrize('quantity', [0, -1, 1.5, True])
def test_invalid_quantity(broker, quantity):
    with pytest.raises(ValueError):
        broker.create_order('bad', 'AAA', 'BUY', quantity, timestamp=at())
    assert broker.audit_events() == ()


def test_explicit_timestamps_and_fill_lifecycle_required(broker):
    with pytest.raises(ValueError, match='timezone-aware'):
        broker.create_order('b', 'AAA', 'BUY', 1, timestamp=datetime(2026, 1, 1))
    broker.create_order('b', 'AAA', 'BUY', 1, timestamp=at())
    with pytest.raises(ValueError, match='ACCEPTED'):
        fill(broker, 'b')
    broker.accept_order('b', timestamp=at(2))
    with pytest.raises(ValueError, match='precedes'):
        fill(broker, 'b', second=1)
    fill(broker, 'b', second=3)
    accepted(broker, 'later', second=0)
    with pytest.raises(ValueError, match='precede an existing'):
        fill(broker, 'later', second=2)
    with pytest.raises(KeyError):
        broker.get_order('missing')


def test_timezone_normalization_preserves_idempotent_fill(broker):
    accepted(broker, 'b')
    first = fill(broker, 'b')
    shifted = at(2).astimezone(timezone(timedelta(hours=2)))
    assert broker.simulate_fill('b', price=100, timestamp=shifted) == first


def test_nonpositive_sell_execution_and_invalid_costs(broker):
    accepted(broker, 'b')
    fill(broker, 'b')
    accepted(broker, 's', 'SELL', second=3)
    with pytest.raises(ValueError, match='Nonpositive'):
        fill(broker, 's', price=1, second=5, slippage_per_share=1)
    for kwargs in ({'commission': -1}, {'slippage_per_share': float('nan')}):
        with pytest.raises(ValueError):
            fill(broker, 's', second=5, **kwargs)
    assert broker.portfolio().positions[0].quantity == 10


def test_rejects_unrelated_database(tmp_path):
    path = tmp_path / 'other.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE unrelated (value TEXT)')
    with pytest.raises(ValueError, match='supported paper-broker'):
        PaperBroker(path)


def test_restart_detects_inconsistent_cash_without_repairing_it(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path) as broker:
        accepted(broker, 'b')
        fill(broker, 'b')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE account SET cash='1' WHERE id=1")
    with pytest.raises(ValueError, match='Ledger reconciliation failed'):
        PaperBroker(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT cash FROM account').fetchone()[0] == '1'


def test_same_timestamp_execution_order_survives_restart(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path) as broker:
        accepted(broker, 'z-buy')
        fill(broker, 'z-buy')
        accepted(broker, 'a-sell', 'SELL', quantity=3)
        fill(broker, 'a-sell', price=120)  # Exactly the same supplied fill time.
        assert [f.order_id for f in broker.fills()] == ['z-buy', 'a-sell']
        state = broker.reconcile()
    with PaperBroker(path) as broker:
        assert broker.reconcile() == state


def test_rollback_after_fill_and_status_updates_are_written(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path) as broker:
        accepted(broker, 'b')
        fill(broker, 'b')
        accepted(broker, 's', 'SELL', quantity=4, second=3)
        before, events = broker.portfolio(), broker.audit_events()
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TRIGGER fail_final_audit BEFORE INSERT ON audit
                       WHEN NEW.event='FILLED' BEGIN SELECT RAISE(ABORT,'audit failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match='audit failure'):
            fill(broker, 's', price=120, second=5)
        assert broker.portfolio() == before
        assert broker.audit_events() == events
        assert broker.get_order('s').status == 'ACCEPTED'
        assert len(broker.fills()) == 1
        assert broker.reconcile() == before


def test_concurrent_same_id_fills_execute_once(tmp_path):
    path = tmp_path / 'paper.sqlite'
    with PaperBroker(path) as broker:
        accepted(broker, 'b')

    def worker(_):
        with PaperBroker(path) as broker:
            return fill(broker, 'b')

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(worker, range(2))
    assert first == second
    with PaperBroker(path) as broker:
        assert broker.reconcile().positions[0].quantity == 10
        assert len(broker.fills()) == 1
        assert [e.event for e in broker.audit_events()] == ['CREATED', 'ACCEPTED', 'FILLED']


def test_partial_sale_is_independent_of_caller_decimal_traps(broker):
    accepted(broker, 'b', quantity=3)
    fill(broker, 'b', price=1, commission=1)
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_FLOOR
        ctx.traps[Inexact] = True
        assert broker.portfolio().positions[0].average_entry_cost > 1
        accepted(broker, 's', 'SELL', quantity=1, second=3)
        result = fill(broker, 's', price=2, second=5)
        assert result.allocated_cost_basis == D('1.333333333333')
        assert broker.reconcile().realized_pnl == D('0.666666666667')
