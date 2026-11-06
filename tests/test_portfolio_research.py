import json

import pytest
from pydantic import ValidationError

from tools.historical_snapshot import HistoricalSnapshot, canonical_json, input_hash
from tools.portfolio_research import (
    FrozenSignals, PortfolioExperiment, PortfolioResearchReport,
    freeze_portfolio_experiment, load_portfolio_experiment, replay_portfolio_experiment,
)
from tools.portfolio_simulator import PortfolioSeries, simulate_portfolio


@pytest.fixture
def inputs():
    tickers = []
    for ticker in ('BBB', 'AAA'):
        bars = []
        for i, day in enumerate(('2020-01-02', '2020-01-03', '2020-01-06')):
            opening = 90 if ticker == 'AAA' and i == 2 else 100
            close = (100, 110, 120)[i] if ticker == 'BBB' else opening
            bars.append(dict(date=day, open=opening, high=max(opening, close) + 1,
                             low=opening - 1, close=close, volume=1000,
                             dividend=1 if i == 2 else 0, split_ratio=2 if i == 1 else 1))
        tickers.append(dict(ticker=ticker, currency='EUR', source='synthetic-v1',
                            calendar='synthetic', price_adjustment='split_adjusted',
                            volume_adjustment='split_adjusted', dividend_convention='recorded_not_applied',
                            split_convention='events_recorded_prices_adjusted', bars=bars))
    snapshot = HistoricalSnapshot.model_validate(dict(schema_version=1, tickers=tickers))
    signals = tuple(FrozenSignals(ticker=t, signal_description='synthetic entries',
                                 entry_signals=(True, False, False), exit_signals=(False,) * 3,
                                 atr_values=(2, 2, 2)) for t in ('BBB', 'AAA'))
    return snapshot, signals


def freeze(inputs, **kwargs):
    settings = dict(initial_cash=1000, max_position_fraction=0.8, risk_fraction=1,
                    fee_rate=0, slippage_rate=0)
    settings.update(kwargs)
    return freeze_portfolio_experiment(*inputs, currency='EUR', **settings)


def replay(experiment):
    return replay_portfolio_experiment(experiment, expected_sha256=input_hash(experiment))


def test_two_ticker_shared_cash_stops_and_reconciliation(inputs):
    experiment = freeze(inputs)
    report = replay(experiment)
    assert report.starting_capital == 1000
    assert report.ending_cash == 720
    assert report.marked_holdings_value == 240
    assert report.ending_capital == 960
    assert report.realized_pnl == -80
    assert report.unrealized_pnl == 40
    assert report.ending_capital == report.ending_cash + report.marked_holdings_value
    assert report.ending_capital == report.starting_capital + report.realized_pnl + report.unrealized_pnl
    assert [p.equity for p in report.equity_curve] == [1000, 1020, 960]
    assert report.total_return_pct == pytest.approx(-4)
    assert report.max_drawdown_pct == pytest.approx(60 / 1020 * 100)
    assert report.completed_trade_count == 1
    trade = report.completed_trades[0]
    assert trade.ticker == 'AAA'
    assert trade.accounting.quantity == 8
    assert trade.accounting.exit_reason == 'stop_gap'
    assert trade.entry_date.isoformat() == '2020-01-03'
    assert trade.exit_date.isoformat() == '2020-01-06'
    assert report.open_positions[0].ticker == 'BBB'
    assert report.open_positions[0].quantity == 2
    assert report.open_positions[0].entry_cost_basis == 200
    assert report.return_basis == 'price_return_excluding_dividends'


def test_deterministic_round_trip_and_order_independence(inputs, tmp_path):
    a = freeze(inputs)
    b = freeze((inputs[0], tuple(reversed(inputs[1]))))
    assert input_hash(a) == input_hash(b)
    path = tmp_path / 'experiment.json'
    path.write_text(canonical_json(a), encoding='utf-8')
    loaded = load_portfolio_experiment(path, expected_sha256=input_hash(a))
    first = replay(a)
    assert canonical_json(first) == canonical_json(replay(loaded))
    assert PortfolioResearchReport.model_validate_json(canonical_json(first)) == first
    assert first.experiment_sha256 == input_hash(a)
    assert first.snapshot_sha256 == input_hash(a.snapshot)
    assert first.signals_sha256 == tuple((s.ticker, input_hash(s)) for s in a.signals)


def test_report_matches_existing_simulator_and_accounts_for_costs(inputs):
    experiment = freeze(inputs, fee_rate=0.001, slippage_rate=0.002)
    report = replay(experiment)
    signals = {s.ticker: s for s in experiment.signals}
    series = {t.ticker: PortfolioSeries(
        dates=tuple(b.date for b in t.bars), opens=tuple(b.open for b in t.bars),
        closes=tuple(b.close for b in t.bars), lows=tuple(b.low for b in t.bars),
        entry_signals=signals[t.ticker].entry_signals,
        exit_signals=signals[t.ticker].exit_signals, atr_values=signals[t.ticker].atr_values,
    ) for t in experiment.snapshot.tickers}
    original = simulate_portfolio(series, **experiment.parameters.model_dump())
    assert report.ending_cash == original.final_cash
    assert report.ending_capital == original.final_equity
    assert tuple(t.accounting for t in report.completed_trades) == tuple(t.trade for t in original.trades)
    assert report.ending_capital == pytest.approx(
        report.starting_capital + report.realized_pnl + report.unrealized_pnl
    )
    p = report.open_positions[0]
    assert p.entry_cost_basis == pytest.approx(p.quantity * p.entry_price * 1.002 * 1.001)
    assert p.unrealized_pnl == pytest.approx(p.marked_value - p.entry_cost_basis)
    assert report.incurred_execution_costs == pytest.approx(
        sum(t.trade.costs for t in original.trades)
        + p.entry_cost_basis - p.quantity * p.entry_price
    )
    for name in ('total_return_pct', 'annualized_return_pct', 'max_drawdown_pct',
                 'sharpe_ratio', 'annualized_volatility_pct', 'trade_expectancy', 'trade_expectancy_pct'):
        assert getattr(report, name) == getattr(original, name)


def test_entry_day_stop_cannot_finance_another_opening_entry(inputs):
    data = inputs[0].model_dump(mode='json')
    data['tickers'][0]['bars'][1]['low'] = 96
    snapshot = HistoricalSnapshot.model_validate(data)
    report = replay(freeze((snapshot, inputs[1]), max_position_fraction=1))
    assert report.open_positions == ()
    assert report.completed_trade_count == 1
    trade = report.completed_trades[0]
    assert trade.ticker == 'AAA'
    assert trade.accounting.quantity == 10
    assert trade.accounting.exit_reason == 'stop_intraday'
    assert trade.entry_date == trade.exit_date
    assert report.ending_cash == report.ending_capital == 970


def test_no_atr_no_trades_and_defaults(inputs):
    signals = tuple(s.model_copy(update=dict(atr_values=None, entry_signals=(False,) * 3)) for s in inputs[1])
    experiment = freeze_portfolio_experiment(inputs[0], signals, currency='EUR')
    report = replay(experiment)
    assert report.parameters.initial_cash == 10000
    assert report.parameters.fee_rate == 0.001
    assert report.parameters.atr_multiplier == 1.5
    assert report.ending_capital == 10000
    assert report.sharpe_ratio is None
    assert report.trade_expectancy is None
    assert report.completed_trade_count == 0


@pytest.mark.parametrize('change', ['currency', 'date', 'dividend_adjusted', 'raw_split'])
def test_incompatible_snapshot_inputs(inputs, change):
    data = inputs[0].model_dump(mode='json')
    t = data['tickers'][0]
    if change == 'currency':
        t['currency'] = 'USD'
    elif change == 'date':
        t['bars'][2]['date'] = '2020-01-07'
    elif change == 'dividend_adjusted':
        t['price_adjustment'] = 'dividend_adjusted'
    else:
        t.update(price_adjustment='unadjusted', split_convention='events_recorded_prices_unadjusted')
    with pytest.raises(ValidationError):
        freeze((HistoricalSnapshot.model_validate(data), inputs[1]))


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'length', 'atr', 'boolean'])
def test_bad_signal_inputs(inputs, change):
    signals = [s.model_dump(mode='json') for s in inputs[1]]
    if change == 'missing':
        signals.pop()
    elif change == 'duplicate':
        signals[1] = signals[0]
    elif change == 'unknown':
        signals[0]['ticker'] = 'UNKNOWN'
    elif change == 'length':
        signals[0]['exit_signals'] = [False]
    elif change == 'atr':
        signals[0]['atr_values'] = [None, 2, 2]
    else:
        signals[0]['entry_signals'] = [1, False, False]
    with pytest.raises(ValidationError):
        freeze((inputs[0], tuple(FrozenSignals.model_validate(s) for s in signals)))


def test_tampering_configuration_and_integrity(inputs, tmp_path):
    experiment = freeze(inputs)
    path = tmp_path / 'experiment.json'
    changed = experiment.model_dump(mode='json')
    changed['parameters']['initial_cash'] = 2000
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='Experiment hash mismatch'):
        load_portfolio_experiment(path, expected_sha256=input_hash(experiment))
    with pytest.raises(ValueError, match='Experiment hash mismatch'):
        replay_portfolio_experiment(PortfolioExperiment.model_validate(changed), expected_sha256=input_hash(experiment))
    changed['snapshot']['tickers'][0]['bars'][0]['volume'] = 999
    with pytest.raises(ValidationError, match='Snapshot hash mismatch'):
        PortfolioExperiment.model_validate(changed)
    with pytest.raises(ValueError, match='Unknown execution parameter'):
        freeze(inputs, aggregate_risk_cap=0.05)


@pytest.mark.parametrize('field,value', [
    ('code_commit', '0' * 40), ('execution_source_sha256', '0' * 64),
    ('python_version', '0.0.0'), ('dependency_versions', [['pydantic', '0']]),
])
def test_provenance_mismatch(inputs, field, value):
    data = freeze(inputs).model_dump(mode='json')
    data['environment'][field] = value
    with pytest.raises(ValueError, match='Replay environment mismatch'):
        replay(PortfolioExperiment.model_validate(data))


def test_required_disclosures_and_immutable_report(inputs):
    report = replay(freeze(inputs))
    text = ' '.join(report.disclosures)
    for phrase in ('No aggregate', 'not trailing', 'Dividends', 'Idealized', 'without liquidation costs'):
        assert phrase in text
    with pytest.raises(ValidationError):
        report.ending_cash = 0
