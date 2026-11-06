from datetime import datetime, time, timedelta, timezone
import sqlite3

import pandas as pd
import pytest
from pydantic import ValidationError

from models.daily_signals import (
    DAILY_UNIVERSE, BarAvailability, DailySignalInputs, ObservedTicker, Session, SessionSchedule,
)
from providers.daily_ohlcv_provider import YahooDailyOHLCVProvider
from providers.paper_broker import PaperBroker
from tools.daily_signal_pipeline import (
    DailySignalStore, freeze_daily_inputs, ingest_daily_signals, load_daily_inputs, replay_daily_signals,
)
from tools.historical_snapshot import Candle, TickerSnapshot, canonical_json, input_hash
from tools.market_regimes import MarketRegime
from tools.quantitative_pipeline import evaluate_mean_reversion


@pytest.fixture
def frozen():
    # Deliberately synthetic weekday schedule, not an asserted real US calendar.
    sessions = []
    day = datetime(2020, 1, 2, tzinfo=timezone.utc).date()
    while len(sessions) < 200:
        if day.weekday() < 5:
            close = time(18) if len(sessions) == 199 else time(21)
            sessions.append(Session(date=day,
                                    opens_at=datetime.combine(day, time(14, 30), timezone.utc),
                                    closes_at=datetime.combine(day, close, timezone.utc)))
        day += timedelta(days=1)
    schedule = SessionSchedule(
        schema_version=1, calendar='US_EQUITIES', source='synthetic frozen schedule v1',
        available_at=datetime(2019, 12, 1, tzinfo=timezone.utc),
        coverage_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        coverage_end=datetime.combine(day + timedelta(days=3), time(), timezone.utc),
        sessions=tuple(sessions),
    )
    fetched = sessions[-1].closes_at + timedelta(minutes=10)
    observed = []
    for ticker in DAILY_UNIVERSE:
        bars = tuple(Candle(date=s.date, open=100, high=101, low=99, close=100,
                            volume=1000, dividend=0, split_ratio=1) for s in sessions)
        snapshot = TickerSnapshot(
            ticker=ticker, currency='USD', source='synthetic frozen daily data v1',
            calendar='US_EQUITIES', price_adjustment='split_adjusted', volume_adjustment='split_adjusted',
            dividend_convention='recorded_not_applied', split_convention='events_recorded_prices_adjusted',
            bars=bars,
        )
        observed.append(ObservedTicker(
            snapshot=snapshot, fetched_at=fetched, finality_source='synthetic final-candle attestation v1',
            availability=tuple(BarAvailability(date=b.date, available_at=fetched, final=True) for b in bars),
        ))
    return schedule, tuple(observed), fetched + timedelta(minutes=5)


class FrozenProvider:
    def __init__(self, observed, fail_ticker=None):
        self.observed = {o.snapshot.ticker: o for o in observed}
        self.fail_ticker = fail_ticker
        self.calls = []

    def fetch_daily(self, ticker, sessions):
        self.calls.append(ticker)
        if ticker == self.fail_ticker:
            raise OSError('synthetic provider failure')
        return self.observed[ticker]


def freeze(frozen):
    schedule, observed, timestamp = frozen
    return freeze_daily_inputs(schedule, observed, decision_at=timestamp)


def replay(inputs):
    return replay_daily_signals(inputs, expected_sha256=input_hash(inputs))


def replace_observed(frozen, change):
    schedule, observed, timestamp = frozen
    records = [o.model_dump(mode='json') for o in observed]
    change(records)
    return schedule, tuple(ObservedTicker.model_validate(o) for o in records), timestamp


def test_six_tickers_both_variants_usd_contract_and_early_close(frozen):
    report = replay(freeze(frozen))
    assert len(report.decisions) == 12
    assert {d.ticker for d in report.decisions} == set(DAILY_UNIVERSE)
    assert {d.variant for d in report.decisions} == {'baseline', 'bear_filtered'}
    assert {d.decision for d in report.decisions} == {'SELL'}  # Equal to SMA; no holdings implied.
    assert {d.price_currency for d in report.decisions} == {'USD'}
    assert all(not d.order_submission_allowed for d in report.decisions)
    assert report.configuration.broker_currency == 'EUR'
    assert report.decision_at.hour == 18  # The supplied early close, not hardcoded 21:00 UTC.
    assert report.signal_date == frozen[0].sessions[-1].date
    assert all(d.decision_at >= frozen[0].sessions[-1].closes_at for d in report.decisions)


def test_real_v1_buy_and_bear_filtered_hold(frozen):
    def changed(records):
        closes = [100] * 190 + [98, 96, 94, 92, 90, 88, 86, 84, 82, 90]
        for record in records:
            for bar, close in zip(record['snapshot']['bars'], closes):
                bar.update(open=close, high=close + 1, low=close - 1, close=close)
    inputs = freeze(replace_observed(frozen, changed))
    report = replay(inputs)
    for decision in report.decisions:
        assert decision.regime == MarketRegime.BEAR
        assert decision.decision == ('BUY' if decision.variant == 'baseline' else 'HOLD')
    ticker = inputs.snapshot.tickers[0]
    entry, atr = evaluate_mean_reversion(ticker.ticker, [b.high for b in ticker.bars],
                                        [b.low for b in ticker.bars], [b.close for b in ticker.bars])
    assert entry.triggered
    assert report.decisions[0].atr == atr


def test_freeze_json_replay_and_restart_idempotency(frozen, tmp_path):
    inputs = freeze(frozen)
    expected = input_hash(inputs)
    path = tmp_path / 'inputs.json'
    path.write_text(canonical_json(inputs), encoding='utf-8')
    loaded = load_daily_inputs(path, expected_sha256=expected)
    assert canonical_json(replay(loaded)) == canonical_json(replay(inputs))
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        first = store.publish('daily-run', inputs)
        assert store.publish('daily-run', loaded) == first
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        stored_inputs, stored_report = store.load('daily-run', expected_sha256=expected)
        assert stored_inputs == inputs
        assert stored_report == first
        assert store.publish('daily-run', inputs) == first
    with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 1


def test_ingestion_is_explicit_and_does_not_create_broker_orders(frozen, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Signal generation attempted a broker action')
    monkeypatch.setattr(PaperBroker, 'create_order', forbidden)
    monkeypatch.setattr(PaperBroker, 'simulate_fill', forbidden)
    provider = FrozenProvider(frozen[1])
    with PaperBroker(tmp_path / 'broker.sqlite') as broker:
        before = broker.portfolio()
        with DailySignalStore(tmp_path / 'daily.sqlite') as store:
            report = ingest_daily_signals(provider, frozen[0], decision_at=frozen[2], store=store, run_id='run')
        assert broker.portfolio() == before
        assert broker.audit_events() == broker.fills() == ()
    assert provider.calls == list(DAILY_UNIVERSE)
    assert len(report.decisions) == 12


def test_ingestion_samples_decision_clock_after_fetch(frozen, tmp_path):
    schedule, observed, decision_at = frozen
    times = iter((observed[0].fetched_at - timedelta(minutes=1), decision_at))
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        report = ingest_daily_signals(FrozenProvider(observed), schedule, clock=lambda: next(times),
                                     store=store, run_id='run')
    assert report.decision_at == decision_at


@pytest.mark.parametrize('bad', ['duplicate', 'missing_middle', 'stale_latest', 'missing_price',
                                 'incomplete', 'future_available', 'before_close_available', 'currency',
                                 'intraday_date', 'naive_timestamp', 'adjustment'])
def test_rejects_bad_candles_or_evidence(frozen, bad):
    def change(records):
        r = records[0]
        bars = r['snapshot']['bars']
        if bad == 'duplicate':
            bars[1]['date'] = bars[0]['date']
        elif bad == 'missing_middle':
            for record in records:  # Even a missing date common to all tickers is rejected.
                del record['snapshot']['bars'][50]
                del record['availability'][50]
        elif bad == 'stale_latest':
            r['snapshot']['bars'].pop()
            r['availability'].pop()
        elif bad == 'missing_price':
            bars[-1]['close'] = None
        elif bad == 'incomplete':
            r['availability'][-1]['final'] = False
        elif bad == 'future_available':
            r['availability'][-1]['available_at'] = (frozen[2] + timedelta(seconds=1)).isoformat()
        elif bad == 'before_close_available':
            r['availability'][-1]['available_at'] = (frozen[0].sessions[-1].closes_at - timedelta(seconds=1)).isoformat()
        elif bad == 'currency':
            r['snapshot']['currency'] = 'EUR'
        elif bad == 'intraday_date':
            bars[-1]['date'] += 'T12:00:00'
        elif bad == 'naive_timestamp':
            r['fetched_at'] = frozen[2].replace(tzinfo=None).isoformat()
        else:
            r['snapshot']['price_adjustment'] = 'dividend_adjusted'
    with pytest.raises(ValueError):
        freeze(replace_observed(frozen, change))


def test_no_decisions_from_an_unfinished_session(frozen):
    schedule, observed, _ = frozen
    with pytest.raises(ValueError, match='200 completed'):
        freeze((schedule, observed, schedule.sessions[-1].closes_at - timedelta(seconds=1)))


@pytest.mark.parametrize('kind', ['coverage', 'unknown_schedule', 'duplicate_schedule', 'short_warmup'])
def test_schedule_fail_closed(frozen, kind):
    schedule, observed, timestamp = frozen
    data = schedule.model_dump(mode='json')
    if kind == 'coverage':
        data['coverage_end'] = (timestamp - timedelta(seconds=1)).isoformat()
    elif kind == 'unknown_schedule':
        data['available_at'] = (timestamp + timedelta(seconds=1)).isoformat()
    elif kind == 'duplicate_schedule':
        data['sessions'].insert(1, data['sessions'][0])
    else:
        data['sessions'].pop(0)
    with pytest.raises(ValueError):
        freeze((SessionSchedule.model_validate(data), observed, timestamp))


@pytest.mark.parametrize('failure', ['provider', 'incomplete', 'wrong_ticker'])
def test_failed_batch_publishes_nothing(frozen, tmp_path, failure):
    if failure == 'incomplete':
        frozen = replace_observed(frozen, lambda records: records[3]['availability'][-1].update(final=False))
    provider = FrozenProvider(frozen[1], fail_ticker='MSFT' if failure == 'provider' else None)
    if failure == 'wrong_ticker':
        provider.observed['MSFT'] = provider.observed['AAPL']
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        with pytest.raises((RuntimeError, ValueError)):
            ingest_daily_signals(provider, frozen[0], decision_at=frozen[2], store=store, run_id='failed')
        with pytest.raises(KeyError):
            store.load('failed', expected_sha256='0' * 64)
    with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_provider_error_keeps_previous_run(frozen, tmp_path):
    inputs = freeze(frozen)
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        before = store.publish('good', inputs)
        with pytest.raises(RuntimeError, match='MSFT'):
            ingest_daily_signals(FrozenProvider(frozen[1], 'MSFT'), frozen[0], decision_at=frozen[2],
                                 store=store, run_id='failed')
        assert store.load('good', expected_sha256=input_hash(inputs))[1] == before


def test_conflicting_run_id_and_changed_provenance(frozen, tmp_path):
    inputs = freeze(frozen)
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        store.publish('run', inputs)
        other = freeze((frozen[0], frozen[1], frozen[2] + timedelta(seconds=1)))
        with pytest.raises(ValueError, match='conflicts'):
            store.publish('run', other)
        assert store.load('run', expected_sha256=input_hash(inputs))[0] == inputs
    changed = inputs.model_dump(mode='json')
    changed['environment']['execution_source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='environment mismatch'):
        replay(DailySignalInputs.model_validate(changed))


def test_input_hashes_and_store_integrity(frozen, tmp_path):
    inputs = freeze(frozen)
    with pytest.raises(ValueError, match='hash mismatch'):
        replay_daily_signals(inputs, expected_sha256='0' * 64)
    changed = inputs.model_dump(mode='json')
    changed['snapshot']['tickers'][0]['bars'][0]['volume'] = 2000
    with pytest.raises(ValueError, match='hash mismatch'):
        DailySignalInputs.model_validate(changed)
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        store.publish('run', inputs)
        with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
            db.execute("UPDATE runs SET signal_date='1900-01-01'")
        with pytest.raises(ValueError, match='metadata mismatch'):
            store.load('run', expected_sha256=input_hash(inputs))


def test_future_fetched_evidence_cannot_be_replayed_into_the_past(frozen):
    timestamp = frozen[1][0].fetched_at - timedelta(seconds=1)
    with pytest.raises(ValueError, match='fetched after decision'):
        freeze((frozen[0], frozen[1], timestamp))


def test_store_rejects_paper_broker_database(tmp_path):
    path = tmp_path / 'broker.sqlite'
    with PaperBroker(path):
        pass
    with pytest.raises(ValueError, match='daily-signal ledger'):
        DailySignalStore(path)


def test_yahoo_adapter_reuses_existing_loader_without_network(frozen, monkeypatch):
    calls = []
    bars = frozen[1][0].snapshot.bars
    data = pd.DataFrame({
        'Open': [b.open for b in bars], 'High': [b.high for b in bars],
        'Low': [b.low for b in bars], 'Close': [b.close for b in bars],
        'Volume': [b.volume for b in bars], 'Dividends': [0.0] * 200, 'Stock Splits': [0.0] * 200,
    }, index=pd.DatetimeIndex([b.date for b in bars]))
    def fake_loader(*args):
        calls.append(args)
        return data
    monkeypatch.setattr('providers.daily_ohlcv_provider.download_historical_data', fake_loader)
    response = YahooDailyOHLCVProvider().fetch_daily('AAPL', frozen[0].sessions)
    assert response.snapshot.currency == 'USD'
    assert all(b.split_ratio == 1 for b in response.snapshot.bars)
    assert all(e.available_at == response.fetched_at for e in response.availability)
    assert all(not e.final for e in response.availability)
    verified = YahooDailyOHLCVProvider(finality_verifier=lambda ticker, candle: True,
                                     finality_source='synthetic verifier, not live market evidence')
    assert all(e.final for e in verified.fetch_daily('AAPL', frozen[0].sessions).availability)
    assert calls == [('AAPL', bars[0].date.isoformat(), (bars[-1].date + timedelta(days=1)).isoformat())] * 2
    data.loc[data.index[0], 'Dividends'] = float('nan')
    with pytest.raises(ValueError, match='corporate-action'):
        YahooDailyOHLCVProvider().fetch_daily('AAPL', frozen[0].sessions)


def test_publish_transaction_failure_leaves_no_partial_run(frozen, tmp_path):
    with DailySignalStore(tmp_path / 'daily.sqlite') as store:
        with sqlite3.connect(tmp_path / 'daily.sqlite') as db:
            db.execute("CREATE TRIGGER abort_run BEFORE INSERT ON runs BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(sqlite3.IntegrityError, match='injected'):
            store.publish('run', freeze(frozen))
        with pytest.raises(KeyError):
            store.load('run', expected_sha256=input_hash(freeze(frozen)))


def test_unfinished_extra_candle_is_rejected_not_silently_trimmed(frozen):
    def extra(records):
        for r in records:
            row = dict(r['snapshot']['bars'][-1])
            row['date'] = (frozen[0].sessions[-1].date + timedelta(days=1)).isoformat()
            r['snapshot']['bars'].append(row)
            r['availability'].append(dict(date=row['date'], available_at=r['fetched_at'], final=False))
    with pytest.raises(ValueError, match='unexpected sessions'):
        freeze(replace_observed(frozen, extra))


def test_snapshot_and_hash_do_not_depend_on_provider_response_order(frozen):
    a = freeze(frozen)
    b = freeze((frozen[0], tuple(reversed(frozen[1])), frozen[2]))
    assert input_hash(a) == input_hash(b)
    assert canonical_json(replay(a)) == canonical_json(replay(b))


def test_timezone_offsets_normalize_without_changing_input_hash(frozen):
    a = freeze(frozen)
    data = a.model_dump(mode='json')
    shifted = frozen[2].astimezone(timezone(timedelta(hours=2)))
    data['decision_at'] = shifted.isoformat()
    assert input_hash(DailySignalInputs.model_validate(data)) == input_hash(a)


def test_strategy_parameters_cannot_be_overridden(frozen):
    data = freeze(frozen).model_dump(mode='json')
    data['configuration']['rsi_period'] = 20
    with pytest.raises(ValidationError):
        DailySignalInputs.model_validate(data)


def test_yahoo_verifier_requires_named_evidence():
    with pytest.raises(ValueError, match='named evidence source'):
        YahooDailyOHLCVProvider(finality_verifier=lambda ticker, candle: True)
