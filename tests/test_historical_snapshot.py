import json

import pytest
from pydantic import ValidationError

from tools.historical_snapshot import (
    HistoricalSnapshot, HistoricalExperiment, canonical_json, input_hash,
    load_snapshot, load_experiment, freeze_experiment, replay_experiment,
)


@pytest.fixture
def payload():
    """Synthetic split-adjusted candles, a 2:1 split and a cash dividend."""
    return {
        'schema_version': 1,
        'tickers': [{
            'ticker': 'AAA', 'currency': 'EUR', 'source': 'synthetic-v1',
            'calendar': 'synthetic-daily', 'price_adjustment': 'split_adjusted',
            'volume_adjustment': 'split_adjusted',
            'dividend_convention': 'recorded_not_applied',
            'split_convention': 'events_recorded_prices_adjusted',
            'bars': [
                {'date': '2020-01-02', 'open': 100, 'high': 101, 'low': 99,
                 'close': 100, 'volume': 1000, 'dividend': 0, 'split_ratio': 1},
                {'date': '2020-01-03', 'open': 100, 'high': 101, 'low': 99,
                 'close': 100, 'volume': 2000, 'dividend': 0, 'split_ratio': 2},
                {'date': '2020-01-06', 'open': 110, 'high': 111, 'low': 109,
                 'close': 110, 'volume': 2000, 'dividend': 1, 'split_ratio': 1},
            ],
        }],
    }


def freeze(payload, **kwargs):
    return freeze_experiment(
        HistoricalSnapshot.model_validate(payload), 'AAA', (True, False, False),
        (False, True, False), signal_description='synthetic frozen signals v1',
        initial_cash=1000, max_position_fraction=1, fee_rate=0, slippage_rate=0,
        **kwargs,
    )


def test_snapshot_round_trip_and_corporate_actions(payload, tmp_path):
    snapshot = HistoricalSnapshot.model_validate(payload)
    path = tmp_path / 'snapshot.json'
    path.write_text(canonical_json(snapshot), encoding='utf-8')
    restored = load_snapshot(path)
    assert restored == snapshot
    assert restored.tickers[0].bars[1].split_ratio == 2
    assert restored.tickers[0].bars[2].dividend == 1
    assert restored.tickers[0].currency == 'EUR'
    assert input_hash(restored) == input_hash(snapshot)
    with pytest.raises(ValidationError):
        restored.tickers[0].currency = 'USD'


def test_canonical_hash_ignores_json_format_and_ticker_order(payload):
    second = dict(payload['tickers'][0], ticker='BBB')
    payload['tickers'].append(second)
    a = HistoricalSnapshot.model_validate(payload)
    payload['tickers'].reverse()
    b = HistoricalSnapshot.model_validate(json.loads(json.dumps(payload, sort_keys=True, indent=4)))
    assert canonical_json(a) == canonical_json(b)
    assert input_hash(a) == input_hash(b)
    second['currency'] = 'USD'
    assert input_hash(HistoricalSnapshot.model_validate(payload)) != input_hash(a)


def test_frozen_replay_matches_exactly_and_records_effective_settings(payload, tmp_path):
    experiment = freeze(payload)
    again = freeze(payload)
    assert input_hash(experiment) == input_hash(again)
    assert experiment.parameters.risk_fraction == 0.01
    assert experiment.parameters.atr_multiplier == 1.5
    assert len(experiment.environment.code_commit) == 40
    assert len(experiment.environment.execution_source_sha256) == 64
    assert experiment.environment.python_version
    assert dict(experiment.environment.dependency_versions).keys() == {'pandas', 'pydantic', 'yfinance'}
    path = tmp_path / 'experiment.json'
    path.write_text(canonical_json(experiment), encoding='utf-8')
    restored = load_experiment(path, expected_sha256=input_hash(experiment))
    first = replay_experiment(experiment)
    assert replay_experiment(restored) == first
    assert first.final_cash == first.final_equity == 1100
    assert first.trades[0].quantity == 10  # No second split adjustment.
    assert experiment.return_basis == 'price_return_excluding_dividends'
    assert first.total_return_pct == pytest.approx(10)  # Dividend is not credited.


def test_changed_dividend_changes_hash_but_not_price_return(payload):
    a = freeze(payload)
    payload['tickers'][0]['bars'][2]['dividend'] = 5
    b = freeze(payload)
    assert input_hash(a.snapshot) != input_hash(b.snapshot)
    assert input_hash(a) != input_hash(b)
    assert replay_experiment(a) == replay_experiment(b)


def test_changed_price_signal_and_parameter_change_hash(payload):
    a = freeze(payload)
    payload['tickers'][0]['bars'][2].update(open=105, high=111, low=104)
    b = freeze(payload)
    assert input_hash(a) != input_hash(b)
    assert replay_experiment(a).final_cash != replay_experiment(b).final_cash
    changed = b.model_dump(mode='json')
    changed['parameters']['fee_rate'] = 0.01
    assert input_hash(HistoricalExperiment.model_validate(changed)) != input_hash(b)
    changed = b.model_dump(mode='json')
    changed['entry_signals'][0] = False
    assert input_hash(HistoricalExperiment.model_validate(changed)) != input_hash(b)


@pytest.mark.parametrize('field', [
    'ticker', 'currency', 'source', 'calendar', 'price_adjustment',
    'volume_adjustment', 'dividend_convention', 'split_convention',
])
def test_missing_metadata_rejected(payload, field):
    del payload['tickers'][0][field]
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


@pytest.mark.parametrize('field,value', [
    ('open', 0), ('close', float('nan')), ('volume', -1), ('high', 98),
    ('low', 102), ('split_ratio', 0), ('dividend', -1), ('open', True),
])
def test_invalid_candle_rejected(payload, field, value):
    payload['tickers'][0]['bars'][0][field] = value
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


@pytest.mark.parametrize('dates', [
    ['2020-01-02', '2020-01-02', '2020-01-06'],
    ['2020-01-03', '2020-01-02', '2020-01-06'],
    ['not-a-date', '2020-01-03', '2020-01-06'],
])
def test_invalid_dates(payload, dates):
    for bar, value in zip(payload['tickers'][0]['bars'], dates):
        bar['date'] = value
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


@pytest.mark.parametrize('value', [1577923200, '2020-01-02T00:00:00', '20200102'])
def test_dates_cannot_be_silently_coerced(payload, value):
    payload['tickers'][0]['bars'][0]['date'] = value
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


@pytest.mark.parametrize('change', ['date', 'calendar', 'ticker'])
def test_inconsistent_universe(payload, change):
    second = json.loads(json.dumps(payload['tickers'][0]))
    second['ticker'] = 'BBB'
    if change == 'date':
        second['bars'][2]['date'] = '2020-01-07'
    elif change == 'calendar':
        second['calendar'] = 'other'
    else:
        second['ticker'] = 'AAA'
    payload['tickers'].append(second)
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


def test_unsupported_version_and_unknown_fields(payload):
    payload['schema_version'] = 2
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)
    payload['schema_version'] = 1
    payload['unknown'] = 'ignored data must never disappear silently'
    with pytest.raises(ValidationError):
        HistoricalSnapshot.model_validate(payload)


def test_corporate_action_unsafe_replay_rejected(payload):
    ticker = payload['tickers'][0]
    ticker.update(price_adjustment='unadjusted', split_convention='events_recorded_prices_unadjusted')
    with pytest.raises(ValidationError, match='unsupported share accounting'):
        freeze(payload)
    ticker.update(price_adjustment='dividend_adjusted', split_convention='events_recorded_prices_adjusted')
    with pytest.raises(ValidationError, match='Dividend-adjusted'):
        freeze(payload)


def test_inconsistent_split_declaration_rejected(payload):
    payload['tickers'][0]['split_convention'] = 'events_recorded_prices_unadjusted'
    with pytest.raises(ValidationError, match='Inconsistent split'):
        HistoricalSnapshot.model_validate(payload)


def test_unadjusted_no_split_is_replayable(payload):
    ticker = payload['tickers'][0]
    ticker.update(price_adjustment='unadjusted', split_convention='events_recorded_prices_unadjusted',
                  volume_adjustment='unadjusted')
    for bar in ticker['bars']:
        bar['split_ratio'] = 1
    assert replay_experiment(freeze(payload)).final_cash == 1100


def test_hash_integrity_and_environment_guard(payload, tmp_path):
    experiment = freeze(payload)
    data = experiment.model_dump(mode='json')
    data['snapshot']['tickers'][0]['bars'][0]['volume'] += 1
    with pytest.raises(ValidationError, match='Snapshot hash mismatch'):
        HistoricalExperiment.model_validate(data)
    path = tmp_path / 'experiment.json'
    path.write_text(canonical_json(experiment), encoding='utf-8')
    with pytest.raises(ValueError, match='Experiment hash mismatch'):
        load_experiment(path, expected_sha256='0' * 64)
    data = experiment.model_dump(mode='json')
    data['environment']['python_version'] = '0.0.0'
    with pytest.raises(ValueError, match='environment mismatch'):
        replay_experiment(HistoricalExperiment.model_validate(data))


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        load_snapshot(path)


def test_frozen_atr_and_cost_replay(payload):
    experiment = freeze_experiment(
        HistoricalSnapshot.model_validate(payload), 'AAA', (True, False, False),
        (False, True, False), atr_values=(2, 2, 2), signal_description='ATR fixture',
        initial_cash=1000,
    )
    a = replay_experiment(experiment)
    b = replay_experiment(HistoricalExperiment.model_validate_json(canonical_json(experiment)))
    assert a == b
    assert a.trades[0].costs > 0
    assert a.final_cash == pytest.approx(1000 + a.trades[0].net_pnl)


@pytest.mark.parametrize('change', ['ticker', 'signals', 'atr', 'parameter'])
def test_invalid_experiment_inputs(payload, change):
    data = freeze(payload).model_dump(mode='json')
    if change == 'ticker':
        data['ticker'] = 'UNKNOWN'
    elif change == 'signals':
        data['entry_signals'] = [1, False, False]
    elif change == 'atr':
        data['atr_values'] = [None, 2, 2]
    else:
        data['parameters']['fee_rate'] = -1
    with pytest.raises(ValidationError):
        HistoricalExperiment.model_validate(data)
