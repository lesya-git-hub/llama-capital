"""Focused tests for the test-only finite synthetic experiment."""
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.synthetic_portfolio_experiment import invented_fixture, run_experiment, shadow_at


@pytest.fixture(scope='module')
def experiment():
    protected = [Path('scripts/sec_match_recon.py'), Path('.env'),
        Path('docs/alpaca_trial_feasibility.md'), Path('docs/tiingo_read_only_trial_design.md'),
        *Path('runs/sprint1v-synthetic-001').glob('*')]
    before = {p: sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError('No provider transport, credentials or network in experiment')
    with patch('providers.alpaca_market_data.load_credentials', forbidden), \
         patch('providers.alpaca_market_data.SingleGETTransport.get', forbidden), \
         patch('http.client.HTTPSConnection', forbidden), patch('socket.create_connection', forbidden):
        report = run_experiment()
    assert before == {p: sha256(p.read_bytes()).hexdigest() for p in before}
    return report


def test_both_portfolios_use_30_shared_sessions_and_cash_benchmark(experiment):
    a, b = (experiment['portfolios'][v]['daily'] for v in ('baseline', 'bear_filtered'))
    calendar, days, _ = invented_fixture()
    assert len(days) == 230 and len(a) == len(b) == 30
    assert [r['session'] for r in a] == [r['session'] for r in b] == [str(d) for d in days[200:]]
    assert all(r['cash_benchmark'] == '10000' for r in a+b)
    assert experiment['warmup_sessions'] == 200 and experiment['temporary_ledgers_removed']


@pytest.mark.parametrize('variant', ['baseline', 'bear_filtered'])
def test_daily_financial_identities_reconcile(experiment, variant):
    for row in experiment['portfolios'][variant]['daily']:
        assert Decimal(row['cash']) >= 0
        assert Decimal(row['equity']) == Decimal(row['cash']) + Decimal(row['exposure'])
        assert Decimal(row['equity']) - 10000 == Decimal(row['realized_pnl']) + Decimal(row['unrealized_pnl'])
        assert all(p['quantity'] > 0 for p in row['positions'])
        assert row['reconciled'] and row['monitoring'] == 'HEALTHY'


@pytest.mark.parametrize('variant', ['baseline', 'bear_filtered'])
def test_signal_proposal_fill_are_distinct_and_later_session(experiment, variant):
    rows = experiment['portfolios'][variant]['daily']
    assert {s['decision'] for r in rows for s in r['signals']} == {'BUY', 'SELL', 'HOLD'}
    previous_positions = {}
    for row in rows:
        assert row['signal_date'] < row['session']
        for proposal in row['proposals']:
            assert proposal['decision_at'] < proposal['execution_at']
            if proposal['side'] == 'SELL':
                assert proposal['quantity'] <= previous_positions[proposal['ticker']]
        previous_positions = {p['ticker']: p['quantity'] for p in row['positions']}
    summary = experiment['portfolios'][variant]['summary']
    assert summary['fills'] == sum(r['fills'] for r in rows)
    assert summary['rejections'] == sum(r['rejections'] for r in rows)
    assert summary['control_failures'] == 0


def test_stops_are_not_executed_or_sell_rejections_bypassed(experiment):
    assert experiment['stops'] == 'RISK_ASSUMPTIONS_ONLY_NOT_EXECUTED'
    rejected_sells = [p for data in experiment['portfolios'].values() for r in data['daily']
        for p in r['proposals'] if p['side'] == 'SELL' and p['status'] == 'REJECTED']
    assert all(p['reasons'] for p in rejected_sells)
    filled_sells = [p for data in experiment['portfolios'].values() for r in data['daily']
        for p in r['proposals'] if p['side'] == 'SELL' and p['status'] == 'FILLED']
    assert filled_sells and all(p['stage'] == 'GATE' and p['reasons'] == ['RISK_APPROVED_AND_FILLED'] for p in filled_sells)


def test_future_values_cannot_change_first_decision():
    calendar, days, paths = invented_fixture()
    before = shadow_at(calendar, days, paths, 199)
    altered = {t: p[:200] + [900] * 30 for t, p in paths.items()}
    assert shadow_at(calendar, days, altered, 199) == before


def test_results_reproduce_exactly(experiment):
    assert run_experiment() == experiment


@pytest.mark.parametrize('variant', ['baseline', 'bear_filtered'])
def test_drawdown_and_return_from_daily_equity(experiment, variant):
    data = experiment['portfolios'][variant]
    peak, worst = Decimal(10000), Decimal(0)
    # Mirror reporting context, not an alternative financial engine.
    from decimal import localcontext
    with localcontext() as context:
        context.prec = 50
        for row in data['daily']:
            equity = Decimal(row['equity'])
            peak = max(peak, equity)
            worst = max(worst, (peak-equity) / peak * 100)
        assert Decimal(data['summary']['max_drawdown_pct']) == worst
        assert Decimal(data['summary']['total_return_pct']) == (equity / 10000 - 1) * 100
