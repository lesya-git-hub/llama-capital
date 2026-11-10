"""Only invented bars and synthetic calendars; never acquire or persist real data."""
from datetime import datetime, time, timezone
import json
import sqlite3

import pytest

import providers.alpaca_market_data as provider
from tests.test_market_verification import fixture as calendar_fixture
from tools.alpaca_shadow import ShadowReport, analyze_shadow_batch
from tools.alpaca_data_validation import AlpacaQualityRejected
from tools.historical_snapshot import input_hash
from tools.market_verification import NEW_YORK
from tools.quantitative_pipeline import evaluate_mean_reversion
from tools.historical_signals import generate_mean_reversion_exits
from tools.market_regimes import classify_market_regime, filter_entries_by_regime, MarketRegime


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Shadow tests must not use network, credentials, processes or databases')
    monkeypatch.setattr(provider.http.client, 'HTTPSConnection', forbidden)
    monkeypatch.setattr(provider.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(provider, 'load_credentials', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)


@pytest.fixture
def sample():
    calendar, observations, _, _, _ = calendar_fixture.__wrapped__()
    days = tuple(s.date for s in calendar.as_daily_schedule().sessions)
    request = provider.DailyBarsRequest(start=calendar.coverage_start, end=days[-1],
        limit=2000, expected_session_dates=days)
    body = {'bars': {}, 'next_page_token': None}
    for o in observations:
        prices = [100] * len(days)
        if o.snapshot.ticker == 'AAPL':
            prices[-15:] = list(range(99, 85, -1)) + [92]
        body['bars'][o.snapshot.ticker] = [dict(
            t=datetime.combine(d, time(), NEW_YORK).astimezone(timezone.utc).isoformat(),
            o=p, h=p+1, l=p-1, c=p, v=1000, n=100, vw=p) for d, p in zip(days, prices)]
    class Mock:
        def get(self, request, credentials, limits):
            return provider.HTTPResponse(200, json.dumps(body).encode())
    acquired = datetime(2020, 11, 11, 12, tzinfo=timezone.utc)
    batch = provider.AlpacaMarketDataAdapter(transport=Mock(),
        credentials=provider.AlpacaCredentials('INVENTED', 'NOT-A-SECRET'), clock=lambda: acquired).fetch(request)
    return batch, calendar


def test_reuses_math_without_promoting_inputs_or_writing(sample, tmp_path, monkeypatch, capsys):
    batch, calendar = sample
    original = input_hash(batch)
    monkeypatch.chdir(tmp_path)
    result = analyze_shadow_batch(batch, calendar)
    assert result.status == 'PROVISIONAL' and not result.trust_admitted and not result.order_submission_allowed
    assert result.feed_coverage == 'PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'
    assert result.finality == result.adjustment_correctness == 'NOT_ESTABLISHED'
    assert result.rights_clearance == 'UNRESOLVED'
    assert len(result.conditions) == 6 and all(r.sessions == 223 for r in result.conditions)
    for row, observation in zip(result.conditions, sorted(batch.observations, key=lambda o: o.symbol)):
        highs, lows, closes = (tuple(getattr(b, field) for b in observation.bars) for field in ('high', 'low', 'close'))
        entry, atr = evaluate_mean_reversion(row.symbol, highs, lows, closes)
        regime = classify_market_regime(highs, lows, closes)
        assert row.baseline_entry_condition == entry.triggered
        assert row.exit_condition == generate_mean_reversion_exits(closes)[-1]
        assert row.bear_filtered_entry_condition == filter_entries_by_regime([entry.triggered], [regime], {MarketRegime.BEAR})[0]
        assert row.regime == regime and row.atr_usd == atr
    assert result.conditions[0].baseline_entry_condition
    assert result == analyze_shadow_batch(batch, calendar)
    assert input_hash(batch) == original and not batch.provider_final
    assert not list(tmp_path.iterdir()) and not capsys.readouterr().out


def test_exact_200_sessions_supported(sample):
    batch, calendar = sample
    first = batch.observations[0].bars[-200].session_date
    request = batch.request.model_copy(update={
        'start': datetime.combine(first, time(), NEW_YORK).astimezone(timezone.utc),
        'expected_session_dates': batch.request.expected_session_dates[-200:]})
    shorter = batch.model_copy(update={'request': request, 'observations': tuple(
        o.model_copy(update={'bars': o.bars[-200:]}) for o in batch.observations)})
    assert all(r.sessions == 200 for r in analyze_shadow_batch(shorter, calendar).conditions)


def test_199_sessions_not_silently_baseline_only(sample):
    batch, calendar = sample
    first = batch.observations[0].bars[-199].session_date
    request = batch.request.model_copy(update={
        'start': datetime.combine(first, time(), NEW_YORK).astimezone(timezone.utc),
        'expected_session_dates': batch.request.expected_session_dates[-199:]})
    shorter = batch.model_copy(update={'request': request, 'observations': tuple(
        o.model_copy(update={'bars': o.bars[-199:]}) for o in batch.observations)})
    with pytest.raises(ValueError, match='200_SESSIONS'):
        analyze_shadow_batch(shorter, calendar)


@pytest.mark.parametrize('failure', ['missing', 'uniform_missing', 'duplicate', 'reversed', 'nan', 'calendar', 'revision'])
def test_quality_holds_stop_before_math(sample, monkeypatch, failure):
    batch, calendar = sample
    previous = ()
    rows = list(batch.observations)
    if failure in ('missing', 'uniform_missing'):
        for index in range(6 if failure == 'uniform_missing' else 1):
            rows[index] = rows[index].model_copy(update={'bars': rows[index].bars[:-1]})
    elif failure == 'duplicate':
        rows[0] = rows[0].model_copy(update={'bars': (*rows[0].bars, rows[0].bars[-1])})
    elif failure == 'reversed':
        rows[0] = rows[0].model_copy(update={'bars': tuple(reversed(rows[0].bars))})
    elif failure in ('nan', 'revision'):
        previous = (batch,) if failure == 'revision' else ()
        bar = rows[0].bars[-1].model_copy(update={'close': float('nan') if failure == 'nan' else 92.5})
        rows[0] = rows[0].model_copy(update={'bars': (*rows[0].bars[:-1], bar)})
    else:
        calendar = None
    changed = batch.model_copy(update={'observations': tuple(rows)})
    def forbidden(*args):
        pytest.fail('Math ran after held quality checks')
    monkeypatch.setattr('tools.alpaca_shadow.evaluate_mean_reversion', forbidden)
    with pytest.raises(AlpacaQualityRejected):
        analyze_shadow_batch(changed, calendar, previous_batches=previous)


@pytest.mark.parametrize('changes', [{'status': 'VERIFIED'}, {'trust_admitted': True}, {'order_submission_allowed': True}])
def test_diagnostic_output_cannot_be_relabelled(sample, changes):
    report = analyze_shadow_batch(*sample)
    with pytest.raises(ValueError):
        ShadowReport.model_validate(report.model_dump(mode='python') | changes)
