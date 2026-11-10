"""Invented offline six-stock data/calendars. Never a real Alpaca sample."""
from datetime import date, datetime, time, timedelta, timezone
from dataclasses import FrozenInstanceError
import json
import math

import pytest

import providers.alpaca_market_data as provider
from models.daily_signals import DAILY_UNIVERSE
from tools.market_verification import CalendarArtifact, ClosedDate, ExchangeSession, Listing, NEW_YORK
from tools.historical_snapshot import input_hash
from tools.alpaca_data_validation import (AlpacaQualityRejected, AlpacaQualityReport,
    AlpacaValidationSession, assess_alpaca_batch, validate_alpaca_batch)

UTC = timezone.utc


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('No network, process or credentials in validation tests')
    monkeypatch.setattr(provider.http.client, 'HTTPSConnection', forbidden)
    monkeypatch.setattr(provider.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(provider, 'load_credentials', forbidden)


def fixtures(start=date(2026,10,26), end=date(2026,10,30), *, holidays=(), exceptional=(), early=()):
    source, version = 'INVENTED-1T-NOT-EXCHANGE-AUTHORITY', 'fixture-1'
    sessions, closed = [], []
    day = start
    while day <= end:
        for exchange in ('XNYS','XNAS'):
            reason = 'weekend' if day.weekday() >= 5 else 'holiday' if day in holidays else 'exceptional_closure' if day in exceptional else None
            if reason:
                closed.append(ClosedDate(date=day, exchange=exchange, reason=reason, source=source, version=version))
            else:
                sessions.append(ExchangeSession(date=day, exchange=exchange, source=source, version=version,
                    opens_at=datetime.combine(day,time(9,30),NEW_YORK),
                    closes_at=datetime.combine(day,time(13) if day in early else time(16),NEW_YORK)))
        day += timedelta(days=1)
    calendar = CalendarArtifact(schema_version=1, scope='synthetic_test', source=source, version=version,
        available_at=datetime(2020,1,1,tzinfo=UTC), coverage_start=start, coverage_end=end+timedelta(days=1),
        listings=tuple(Listing(ticker=t,exchange='XNAS' if i%2 else 'XNYS') for i,t in enumerate(DAILY_UNIVERSE)),
        sessions=tuple(sessions),closed_dates=tuple(closed))
    days = tuple(s.date for s in calendar.as_daily_schedule().sessions)
    request = provider.DailyBarsRequest(start=start,end=end,expected_session_dates=days)
    body={'bars':{s:[dict(t=datetime.combine(d,time(),NEW_YORK).astimezone(UTC).isoformat().replace('+00:00','Z'),
        o=100,h=105,l=95,c=102,v=1000,n=100,vw=101) for d in days] for s in DAILY_UNIVERSE},'next_page_token':None}
    class Mock:
        def get(self, request, credentials, limits):
            return provider.HTTPResponse(200,json.dumps(body).encode())
    acquired=datetime.combine(end+timedelta(days=1),time(12),UTC)
    adapter=provider.AlpacaMarketDataAdapter(transport=Mock(),
        credentials=provider.AlpacaCredentials('INVENTED-KEY','INVENTED-SECRET'),clock=lambda:acquired)
    return adapter.fetch(request),calendar


def codes(report): return {i.code for i in report.issues}


def mutate_bar(batch, **changes):
    observation=batch.observations[0]
    bar=observation.bars[0].model_copy(update=changes)
    obs=observation.model_copy(update={'bars':(bar,*observation.bars[1:])})
    return batch.model_copy(update={'observations':(obs,*batch.observations[1:])})


def reject(batch, calendar, code=None, **kwargs):
    with pytest.raises(AlpacaQualityRejected) as caught:
        validate_alpaca_batch(batch,calendar,**kwargs)
    assert caught.value.report.quality_outcome=='HELD'
    assert caught.value.report.status=='PROVISIONAL'
    if code: assert code in codes(caught.value.report)
    return caught.value.report


def test_positive_in_memory_metadata_evidence_boundary_and_no_mutation(tmp_path,monkeypatch):
    batch,calendar=fixtures()
    before=(input_hash(batch),input_hash(calendar))
    monkeypatch.chdir(tmp_path)
    report=validate_alpaca_batch(batch,calendar)
    assert report.status=='PROVISIONAL' and report.quality_outcome=='CHECKS_PASSED'
    assert not report.issues and len(report.symbols)==6
    assert all(s.count==5 and not s.missing_dates and not s.extra_dates for s in report.symbols)
    assert report.feed_coverage=='PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'
    assert report.adjustment_assessment=='PROVIDER_CLAIM_NOT_INDEPENDENTLY_VERIFIED'
    assert report.candle_finality==report.corporate_action_evidence=='NOT_ESTABLISHED'
    assert report.rights_clearance=='UNRESOLVED' and not report.trust_admitted
    assert report.calendar_scope=='synthetic_test'
    assert report.input_sha256==before[0] and report.calendar_sha256==before[1]
    assert before==(input_hash(batch),input_hash(calendar)) and list(tmp_path.iterdir())==[]
    assert assess_alpaca_batch(batch,calendar)==report


@pytest.mark.parametrize('start,end,hours',[(date(2026,3,6),date(2026,3,10),(5,4,4)),
    (date(2026,10,30),date(2026,11,3),(4,5,5))])
def test_dst_session_dates_match_existing_calendar(start,end,hours):
    batch,calendar=fixtures(start,end)
    assert tuple(b.timestamp.hour for b in batch.observations[0].bars)==hours
    assert validate_alpaca_batch(batch,calendar).quality_outcome=='CHECKS_PASSED'


@pytest.mark.parametrize('kind',['holidays','exceptional'])
def test_calendar_explicit_closure_not_inferred_weekday(kind):
    closed=date(2026,10,28)
    batch,calendar=fixtures(**{kind:(closed,)})
    report=validate_alpaca_batch(batch,calendar)
    assert report.symbols[0].count==4 and closed.isoformat() not in report.symbols[0].expected_dates


def test_early_close_is_completed_session_not_provider_finality():
    batch,calendar=fixtures(early=(date(2026,10,30),))
    report=validate_alpaca_batch(batch,calendar)
    assert report.quality_outcome=='CHECKS_PASSED' and report.candle_finality=='NOT_ESTABLISHED'
    assert not batch.provider_final


def test_missing_calendar_and_invalid_calendar_refuse():
    batch,calendar=fixtures()
    reject(batch,None,'MISSING_FROZEN_CALENDAR')
    reject(batch,object(),'INVALID_OR_DIVERGENT_CALENDAR')
    invalid=calendar.model_copy(update={'closed_dates':(ClosedDate(date=date(2026,10,26),exchange='XNYS',
        reason='holiday',source=calendar.source,version=calendar.version),)})
    reject(batch,invalid,'INVALID_OR_DIVERGENT_CALENDAR')


def test_divergent_exchanges_not_merged_or_guessed():
    batch,calendar=fixtures()
    rows=list(calendar.sessions)
    rows[0]=rows[0].model_copy(update={'closes_at':rows[0].closes_at-timedelta(hours=1)})
    reject(batch,calendar.model_copy(update={'sessions':tuple(rows)}),'INVALID_OR_DIVERGENT_CALENDAR')


@pytest.mark.parametrize('change',['missing_one','missing_all','extra','duplicate','order','missing_symbol','duplicate_symbol','extra_symbol'])
def test_incomplete_or_inconsistent_batches_rejected(change):
    batch,calendar=fixtures()
    observations=list(batch.observations)
    if change=='missing_one': observations[0]=observations[0].model_copy(update={'bars':observations[0].bars[:-1]})
    elif change=='missing_all': observations=[o.model_copy(update={'bars':o.bars[:-1]}) for o in observations]
    elif change=='extra':
        bar=observations[0].bars[-1].model_copy(update={'timestamp':datetime(2026,10,31,4,tzinfo=UTC),'session_date':date(2026,10,31)})
        observations[0]=observations[0].model_copy(update={'bars':(*observations[0].bars,bar)})
    elif change=='duplicate': observations[0]=observations[0].model_copy(update={'bars':(*observations[0].bars,observations[0].bars[0])})
    elif change=='order': observations[0]=observations[0].model_copy(update={'bars':tuple(reversed(observations[0].bars))})
    elif change=='missing_symbol': observations.pop()
    elif change=='duplicate_symbol': observations[-1]=observations[0]
    else: observations[-1]=observations[-1].model_copy(update={'symbol':'SPY'})
    report=reject(batch.model_copy(update={'observations':tuple(observations)}),calendar)
    if change.startswith('missing_') and 'symbol' not in change: assert 'MISSING_SESSIONS' in codes(report)
    if change=='duplicate': assert 'DUPLICATE_SESSIONS' in codes(report)
    if change=='order': assert 'NONCHRONOLOGICAL_SESSIONS' in codes(report)


def test_bar_on_holiday_is_extra_even_when_caller_expected_it():
    batch,_=fixtures()
    _,calendar=fixtures(holidays=(date(2026,10,28),))
    report=reject(batch,calendar,'EXTRA_OR_CLOSED_SESSIONS')
    assert 'CALLER_EXPECTATIONS_CONFLICT_WITH_CALENDAR' in codes(report)


@pytest.mark.parametrize('field,value', [('open',float('nan')),('high',float('inf')),('low',0.0),
    ('close',-1.0),('high',99.0),('volume',-1.0),('volume',1.5),('volume',float(2**53)),
    ('volume',True),('trade_count',1.5),('trade_count',True),('trade_count',-1),
    ('trade_count',0),('vwap',float('nan')),('vwap',0.0),('vwap',200.0),('vwap',94.0)])
def test_malformed_ohlcv_volume_vwap_and_counts(field,value):
    batch,calendar=fixtures()
    reject(mutate_bar(batch,**{field:value}),calendar)


def test_nonnegative_integer_zero_volume_and_optional_fields():
    batch,calendar=fixtures()
    changed=mutate_bar(batch,volume=0.0,trade_count=0,vwap=None)
    assert validate_alpaca_batch(changed,calendar).quality_outcome=='CHECKS_PASSED'
    assert validate_alpaca_batch(mutate_bar(batch,trade_count=None,vwap=None),calendar).quality_outcome=='CHECKS_PASSED'
    reject(mutate_bar(batch,volume=0.0),'not a calendar','INVALID_OR_DIVERGENT_CALENDAR')
    reject(mutate_bar(batch,volume=0.0),calendar,'TRADE_COUNT_VOLUME_INCONSISTENCY')


def test_split_adjusted_volume_not_assumed_to_bound_original_trade_count():
    batch,calendar=fixtures()
    changed=mutate_bar(batch,volume=5.0,trade_count=100)
    report=validate_alpaca_batch(changed,calendar)
    assert report.corporate_action_evidence=='NOT_ESTABLISHED'


@pytest.mark.parametrize('kind',['naive','nonmidnight','wrong_date','nonutc'])
def test_timestamp_label_errors(kind):
    batch,calendar=fixtures()
    first=batch.observations[0].bars[0]
    changes={'timestamp':first.timestamp.replace(tzinfo=None)} if kind=='naive' else (
        {'timestamp':first.timestamp+timedelta(hours=1)} if kind=='nonmidnight' else (
        {'session_date':first.session_date+timedelta(days=1)} if kind=='wrong_date' else
        {'timestamp':first.timestamp.astimezone(timezone(timedelta(hours=2)))}))
    reject(mutate_bar(batch,**changes),calendar)


def test_request_calendar_coverage_and_availability():
    batch,calendar=fixtures()
    # A valid but shorter frozen calendar must not trim the requested window.
    _,short=fixtures(end=date(2026,10,29))
    reject(batch,short,'CALENDAR_DOES_NOT_COVER_REQUEST')
    reject(batch,calendar.model_copy(update={'available_at':batch.acquired_start+timedelta(seconds=1)}),
        'CALENDAR_UNAVAILABLE_AT_ACQUISITION')
    req=batch.request.model_copy(update={'start':batch.request.start+timedelta(hours=1),'expected_session_dates':None})
    reject(batch.model_copy(update={'request':req}),calendar,'PARTIAL_SESSION_REQUEST')


def test_completed_api_response_and_elapsed_time_do_not_grant_finality():
    batch,calendar=fixtures()
    very_late=batch.model_copy(update={'acquired_start':batch.acquired_start+timedelta(days=300),
        'acquired_end':batch.acquired_end+timedelta(days=300)})
    report=validate_alpaca_batch(very_late,calendar)
    assert report.candle_finality=='NOT_ESTABLISHED' and not report.trust_admitted


@pytest.mark.parametrize('field,value',[('status','VERIFIED'),('provider_final',True),('pagination_complete',False)])
def test_trust_or_incomplete_metadata_cannot_be_forged(field,value):
    batch,calendar=fixtures()
    reject(batch.model_copy(update={field:value}),calendar,'INVALID_BATCH_SCHEMA')


def test_feed_adjustment_currency_and_universe_not_relaxed():
    batch,calendar=fixtures()
    for changes in ({'feed':'sip'},{'adjustment':'all'},{'currency':'EUR'},{'symbols':('AAPL',)}):
        req=batch.request.model_copy(update=changes)
        reject(batch.model_copy(update={'request':req}),calendar)


def test_revision_is_conflict_not_accepted_corporate_action_repair():
    batch,calendar=fixtures()
    # Invented split-like halving is not an explanation for changed historical bars.
    changed=mutate_bar(batch,open=50.0,high=52.5,low=47.5,close=51.0,vwap=50.5,volume=2000.0)
    old_digest=input_hash(batch)
    report=reject(changed,calendar,'UNVERIFIED_REVISION_CONFLICT',previous_batches=(batch,))
    assert report.adjustment_assessment=='PROVIDER_CLAIM_NOT_INDEPENDENTLY_VERIFIED'
    assert input_hash(batch)==old_digest


def test_identical_contents_later_receipt_not_a_revision_or_finality():
    batch,calendar=fixtures()
    later=batch.model_copy(update={'acquired_start':batch.acquired_start+timedelta(minutes=1),
        'acquired_end':batch.acquired_end+timedelta(minutes=1)})
    report=validate_alpaca_batch(later,calendar,previous_batches=(batch,))
    assert report.history_batches_compared==1 and report.candle_finality=='NOT_ESTABLISHED'


def test_revision_on_overlapping_different_request_window_detected():
    batch,calendar=fixtures()
    later,_=fixtures(start=date(2026,10,28))
    changed=mutate_bar(later,close=103.0)
    reject(changed,calendar,'UNVERIFIED_REVISION_CONFLICT',previous_batches=(batch.model_copy(update={
        'acquired_start':batch.acquired_start-timedelta(days=1),'acquired_end':batch.acquired_end-timedelta(days=1)}),))


def test_dividend_or_price_jump_not_inferred_as_adjustment_evidence():
    batch,calendar=fixtures()
    changed=mutate_bar(batch,open=50.0,high=55.0,low=45.0,close=52.0,vwap=51.0)
    report=validate_alpaca_batch(changed,calendar)
    assert report.quality_outcome=='CHECKS_PASSED'
    assert report.requested_adjustment=='split' and report.corporate_action_evidence=='NOT_ESTABLISHED'
    assert not hasattr(changed.observations[0].bars[0],'dividend')


def test_session_keeps_original_and_conflicting_versions_in_memory(tmp_path,monkeypatch):
    batch,calendar=fixtures(); session=AlpacaValidationSession()
    monkeypatch.chdir(tmp_path)
    first=session.validate(batch,calendar)
    changed=mutate_bar(batch,close=103.0)
    with pytest.raises(AlpacaQualityRejected):session.validate(changed,calendar)
    with pytest.raises(AlpacaQualityRejected):session.validate(batch,calendar)
    assert len(session.history)==3 and session.history[0].report==first
    assert session.history[0].batch==batch and session.history[1].batch==changed
    assert all(r.report.status=='PROVISIONAL' for r in session.history)
    assert list(tmp_path.iterdir())==[]
    with pytest.raises(FrozenInstanceError):session.history[0].batch=None


def test_invalid_prior_history_stays_held_and_capacity_does_not_drop_evidence():
    batch,calendar=fixtures(); session=AlpacaValidationSession(max_observations=2)
    with pytest.raises(AlpacaQualityRejected):session.validate(object(),calendar)
    with pytest.raises(AlpacaQualityRejected) as caught:session.validate(batch,calendar)
    assert 'INVALID_REVISION_HISTORY' in codes(caught.value.report)
    before=session.history
    with pytest.raises(ValueError,match='CAPACITY'):session.validate(batch,calendar)
    assert session.history==before


def test_future_or_invalid_history_not_silently_ignored():
    batch,calendar=fixtures()
    future=batch.model_copy(update={'acquired_end':batch.acquired_end+timedelta(seconds=1)})
    reject(batch,calendar,'REVISION_HISTORY_NOT_PRIOR',previous_batches=(future,))
    reject(batch,calendar,'INVALID_REVISION_HISTORY',previous_batches=(None,))


def test_report_scope_cannot_be_promoted():
    batch,calendar=fixtures(); report=validate_alpaca_batch(batch,calendar)
    for change in ({'status':'ADMITTED'},{'trust_admitted':True},{'candle_finality':'VERIFIED'}):
        with pytest.raises(ValueError):AlpacaQualityReport.model_validate(report.model_dump(mode='python')|change)
