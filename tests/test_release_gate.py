from datetime import date, timedelta
from math import sin

import pytest
from pydantic import ValidationError

from tools.historical_snapshot import HistoricalSnapshot, input_hash
from tools.historical_signals import generate_historical_signals, generate_mean_reversion_exits
from tools.market_regimes import generate_historical_regimes
from tools.portfolio_research import FrozenSignals, freeze_portfolio_experiment, replay_portfolio_experiment
from tools.release_gate import check_portfolio_release_gate, validate_holdout_boundary


@pytest.fixture
def experiment():
    dates = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6), date(2020, 1, 7))
    tickers = []
    signals = []
    for ticker in ('AAA', 'BBB'):
        prices = (100, 100, 90, 100) if ticker == 'AAA' else (100, 100, 110, 120)
        tickers.append(dict(
            ticker=ticker, currency='USD', source='release-gate-synthetic', calendar='synthetic',
            price_adjustment='split_adjusted', volume_adjustment='split_adjusted',
            dividend_convention='recorded_not_applied', split_convention='events_recorded_prices_adjusted',
            bars=[dict(date=d, open=p, high=p+1, low=p-1, close=p, volume=1000,
                       dividend=0, split_ratio=1) for d, p in zip(dates, prices)],
        ))
        signals.append(FrozenSignals(ticker=ticker, signal_description='release-gate synthetic',
                                     entry_signals=(True, False, False, False),
                                     exit_signals=(False,) * 4, atr_values=(2,) * 4))
    return freeze_portfolio_experiment(
        HistoricalSnapshot.model_validate(dict(schema_version=1, tickers=tickers)), tuple(signals),
        currency='USD', initial_cash=1000, max_position_fraction=0.6, risk_fraction=1,
    )


def test_release_gate_deterministic_replay_and_accounting(experiment):
    digest = input_hash(experiment)
    a = check_portfolio_release_gate(experiment, expected_sha256=digest)
    b = check_portfolio_release_gate(experiment, expected_sha256=digest)
    assert a == b
    assert len(a.report_sha256) == 64
    assert a.scope == 'offline_software_invariants_only'
    assert 'execution_provenance' in a.checks


@pytest.mark.parametrize('tamper', ['hash', 'provenance', 'currency', 'calendar'])
def test_release_gate_rejects_inconsistent_inputs(experiment, tamper):
    data = experiment.model_dump(mode='json')
    if tamper == 'hash':
        expected = '0' * 64
    else:
        if tamper == 'provenance':
            data['environment']['code_commit'] = '0' * 40
        elif tamper == 'currency':
            data['currency'] = 'EUR'
        else:
            data['snapshot']['tickers'][0]['bars'][-1]['date'] = '2020-01-08'
        expected = input_hash(experiment)
    with pytest.raises(ValueError):
        checked = type(experiment).model_validate(data)
        # Let provenance reach its specific runtime guard rather than hash mismatch.
        if tamper == 'provenance':
            expected = input_hash(checked)
        check_portfolio_release_gate(checked, expected_sha256=expected)


def test_gate_detects_inconsistent_report(experiment, monkeypatch):
    original = replay_portfolio_experiment(experiment, expected_sha256=input_hash(experiment))
    changed = original.model_copy(update={'ending_cash': original.ending_cash + 1})
    monkeypatch.setattr('tools.release_gate.replay_portfolio_experiment', lambda *a, **k: changed)
    with pytest.raises(ValueError, match='Reconciliation failed'):
        check_portfolio_release_gate(experiment, expected_sha256=input_hash(experiment))


def test_gate_detects_nondeterminism(experiment, monkeypatch):
    original = replay_portfolio_experiment(experiment, expected_sha256=input_hash(experiment))
    outputs = iter((original, original.model_copy(update={'ending_cash': original.ending_cash + 1})))
    monkeypatch.setattr('tools.release_gate.replay_portfolio_experiment', lambda *a, **k: next(outputs))
    with pytest.raises(ValueError, match='Nondeterministic'):
        check_portfolio_release_gate(experiment, expected_sha256=input_hash(experiment))


def boundary(dates, **kwargs):
    settings = dict(training_start=date(2020, 1, 1), training_end=date(2025, 1, 1),
                    holdout_start=date(2025, 1, 1), holdout_end=date(2026, 11, 1))
    settings.update(kwargs)
    return validate_holdout_boundary(dates, **settings)


def test_holdout_boundary_preserves_preceding_signal_and_exclusive_end():
    dates = tuple(date(2024, 1, 1) + timedelta(days=i) for i in range(1100))
    start, end = boundary(dates)
    assert dates[start] == date(2024, 12, 31)
    assert dates[start + 1] == date(2025, 1, 1)
    assert dates[end - 1] == date(2026, 10, 31)
    assert dates[end] == date(2026, 11, 1)


@pytest.mark.parametrize('case', ['empty', 'no_holdout', 'first_row', 'short_history',
                                  'overlap', 'reversed_end', 'duplicate', 'bad_history'])
def test_invalid_holdout_boundaries(case):
    dates = tuple(date(2024, 1, 1) + timedelta(days=i) for i in range(800))
    kwargs = {}
    if case == 'empty':
        dates = ()
    elif case == 'no_holdout':
        dates = dates[:10]
    elif case == 'first_row':
        dates = (date(2025, 1, 1), date(2025, 1, 2))
    elif case == 'short_history':
        dates = (date(2024, 12, 31), date(2025, 1, 1))
    elif case == 'overlap':
        kwargs['training_end'] = date(2025, 2, 1)
    elif case == 'reversed_end':
        kwargs['holdout_end'] = date(2024, 1, 1)
    elif case == 'duplicate':
        dates = (dates[0],) + dates
    else:
        kwargs['minimum_history'] = 0
    with pytest.raises(ValueError):
        boundary(dates, **kwargs)


def test_real_signal_regime_and_exit_prefixes_are_causal():
    cut = 210
    closes = [100 + 12 * sin(i / 7) for i in range(230)]
    changed = closes[:cut] + [50 + i for i in range(20)]

    def evaluate(values):
        highs = [v + 1 for v in values]
        lows = [v - 1 for v in values]
        entries, atr = generate_historical_signals(
            ticker='SYNTH', highs=highs, lows=lows, closes=values,
            volumes=[1000] * len(values), strategy='mean_reversion',
        )
        return entries, atr, generate_mean_reversion_exits(values), generate_historical_regimes(highs, lows, values)

    full = evaluate(closes)
    perturbed = evaluate(changed)
    prefix = evaluate(closes[:cut])
    for original, future_changed, truncated in zip(full, perturbed, prefix):
        assert original[:cut] == future_changed[:cut] == truncated


def test_portfolio_future_suffix_does_not_change_prior_execution(experiment):
    original = replay_portfolio_experiment(experiment, expected_sha256=input_hash(experiment))
    data = experiment.snapshot.model_dump(mode='json')
    for ticker in data['tickers']:
        ticker['bars'][-1].update(open=150, high=161, low=149, close=160)
    changed = freeze_portfolio_experiment(
        HistoricalSnapshot.model_validate(data), experiment.signals, currency=experiment.currency,
        **experiment.parameters.model_dump(),
    )
    report = replay_portfolio_experiment(changed, expected_sha256=input_hash(changed))
    assert original.equity_curve[:-1] == report.equity_curve[:-1]
    assert original.completed_trades == report.completed_trades
