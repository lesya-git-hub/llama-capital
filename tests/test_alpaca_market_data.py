"""Deterministic invented responses only; network is forbidden in this module."""
from datetime import date, datetime, timedelta, timezone
import json
import io
import pickle
import subprocess
import traceback

import pytest

import providers.alpaca_market_data as module
from providers.alpaca_market_data import (AlpacaCredentials, AlpacaDataError, AlpacaDailyBatch,
    AlpacaMarketDataAdapter, DailyBarsRequest, HTTPResponse, SingleGETTransport, TransportLimits,
    _http_once, load_credentials)
from models.daily_signals import DAILY_UNIVERSE

KEY, SECRET = 'INVENTED-KEY-NOT-A-CREDENTIAL', 'INVENTED-SECRET-NOT-A-CREDENTIAL'
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
DAYS = tuple(date(2026, 10, d) for d in range(26, 31))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Network is forbidden in offline tests')
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', forbidden)
    monkeypatch.setattr(module.subprocess, 'Popen', forbidden)


def request(**changes):
    return DailyBarsRequest(**(dict(start='2026-10-26', end='2026-10-30', expected_session_dates=DAYS) | changes))


def payload(symbols=DAILY_UNIVERSE):
    return {'bars': {s: [dict(t=f'2026-10-{d}T04:00:00Z', o=100, h=105, l=95, c=102,
        v=1000, n=100, vw=101.25) for d in range(26, 31)] for s in symbols}, 'next_page_token': None}


def response(value=None, **changes):
    return HTTPResponse(**(dict(status=200, body=json.dumps(payload() if value is None else value).encode()) | changes))


class MockTransport:
    def __init__(self, value):
        self.value, self.calls = value, []
    def get(self, req, credentials, limits):
        self.calls.append((req.url, limits))  # No credentials captured in logs/test diagnostics.
        if isinstance(self.value, Exception): raise self.value
        return self.value


def adapter(value=None, **kwargs):
    transport = MockTransport(response() if value is None else value)
    return AlpacaMarketDataAdapter(transport=transport, credentials=AlpacaCredentials(KEY, SECRET),
        clock=lambda: NOW, **kwargs), transport


def test_complete_batch_metadata_provisional_no_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client, transport = adapter()
    result = client.fetch(request())
    assert len(transport.calls) == 1 and len(result.observations) == 6
    assert all(len(o.bars) == 5 for o in result.observations)
    assert tuple(o.symbol for o in result.observations) == DAILY_UNIVERSE
    assert result.status == 'PROVISIONAL' and result.scope == 'unverified'
    assert not result.provider_final and not result.calendar_verified and result.publication_time is None
    assert result.request.feed == 'iex' and result.request.adjustment == 'split' and result.request.currency == 'USD'
    assert result.session_coverage == 'CALLER_EXPECTATIONS_MATCHED'
    assert result.receipt_clock == 'local_unattested' and result.acquired_start == NOW == result.acquired_end
    assert result.corporate_action_fields == 'not_supplied'
    bar = result.observations[0].bars[0]
    assert bar.open == 100.0 and bar.volume == 1000.0 and bar.vwap == 101.25
    assert bar.timestamp.utcoffset() == timedelta(0) and bar.session_date == DAYS[0]
    assert not hasattr(bar, 'dividend') and not hasattr(bar, 'split_ratio')
    assert not hasattr(client, 'publish') and not hasattr(result, 'as_observed')
    assert list(tmp_path.iterdir()) == []
    assert KEY not in repr(result) and SECRET not in repr(result)


def test_subset_configurable_and_no_calendar_inference():
    client, transport = adapter(response(payload(('AAPL',))))
    result = client.fetch(request(symbols=('AAPL',), expected_session_dates=None))
    assert len(result.observations) == 1 and result.session_coverage == 'UNVERIFIED'
    assert not result.calendar_verified and len(transport.calls) == 1


def test_exact_sanitized_url_and_date_boundaries():
    req = request(symbols=('AAPL',), end='2026-10-31T03:59:59Z')
    assert req.url == 'https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&timeframe=1Day&start=2026-10-26T04%3A00%3A00Z&end=2026-10-31T03%3A59%3A59Z&adjustment=split&feed=iex&currency=USD&limit=100&sort=asc'
    assert request().end == datetime(2026, 10, 31, 3, 59, 59, 999999, tzinfo=timezone.utc)
    assert request(start='2026-11-02', end='2026-11-02', expected_session_dates=None).start.hour == 5


@pytest.mark.parametrize('change', [dict(feed='sip'), dict(adjustment='all'), dict(currency='EUR'),
    dict(timeframe='1Min'), dict(limit=True), dict(limit=0), dict(limit=10001), dict(start='2026-10-26T04:00:00'),
    dict(start=12345), dict(end='2026-10-25'), dict(symbols=('AAPL','AAPL')), dict(symbols=('AAPL,MSFT',)),
    dict(symbols=()), dict(symbols=('aapl',)), dict(expected_session_dates=(DAYS[1],DAYS[0])),
    dict(expected_session_dates=()), dict(expected_session_dates=('2026-10-26T00:00:00',)),
    dict(symbols={'AAPL','MSFT'})])
def test_invalid_requests_fail_before_transport(change):
    with pytest.raises(ValueError): request(**change)


def test_unapproved_symbol_and_future_dates_never_request():
    client, transport = adapter()
    for req in (request(symbols=('SPY',)), request(start='2099-01-01',end='2099-01-02',expected_session_dates=None)):
        with pytest.raises(AlpacaDataError): client.fetch(req)
    assert transport.calls == []


def test_explicit_alternate_permitted_universe():
    client, _ = adapter(response(payload(('SPY',))), permitted_symbols=('SPY',))
    assert client.fetch(request(symbols=('SPY',))).observations[0].symbol == 'SPY'


@pytest.mark.parametrize('bad', ['missing_symbol','extra_symbol','empty','duplicate_date','unordered','misaligned',
    'all_missing_date','missing_token','unknown_root','token','empty_token','wrong_bars_type'])
def test_incomplete_duplicate_or_paginated_response_fails_closed(bad):
    body = payload()
    first = DAILY_UNIVERSE[0]
    if bad == 'missing_symbol': del body['bars'][first]
    elif bad == 'extra_symbol': body['bars']['SPY'] = body['bars'][first]
    elif bad == 'empty': body['bars'][first] = []
    elif bad == 'duplicate_date': body['bars'][first].append(body['bars'][first][0])
    elif bad == 'unordered': body['bars'][first].reverse()
    elif bad == 'misaligned': body['bars'][first].pop()
    elif bad == 'all_missing_date':
        for rows in body['bars'].values(): rows.pop()
    elif bad == 'missing_token': del body['next_page_token']
    elif bad == 'unknown_root': body['extra'] = SECRET
    elif bad == 'token': body['next_page_token'] = 'INVENTED-PAGE'
    elif bad == 'empty_token': body['next_page_token'] = ''
    else: body['bars'] = []
    client, transport = adapter(response(body))
    with pytest.raises(AlpacaDataError): client.fetch(request())
    assert len(transport.calls) == 1


@pytest.mark.parametrize('field,value', [('o',True),('h','105'),('l',-1),('c',0),('v',-1),('v',False),
    ('n',1.5),('n',True),('n',-1),('vw',0),('h',99),('t','2026-10-26'),('t',1770000000),
    ('t','2026-10-26T04:00:00'),('t','2026-10-26T05:00:00Z'),('t','2026-10-26T04:00:00+01:00'),
    ('t','2026-10-25T04:00:00Z'),('t','2026-02-30T05:00:00Z')])
def test_malformed_values_dates_and_timestamps(field,value):
    body=payload(); body['bars'][DAILY_UNIVERSE[0]][0][field]=value
    client, transport = adapter(response(body))
    with pytest.raises(AlpacaDataError): client.fetch(request())
    assert len(transport.calls) == 1


@pytest.mark.parametrize('body', [b'not json',b'{"bars":{},"bars":{},"next_page_token":null}',
    b'{"bars":NaN,"next_page_token":null}', b'\xff', b'[]'])
def test_invalid_json(body):
    client,_=adapter(response(body=body))
    with pytest.raises(AlpacaDataError): client.fetch(request())


@pytest.mark.parametrize('bad', ['nonfinite','underflow','overflow','missing_field','unknown_field'])
def test_numeric_loss_and_schema_errors(bad):
    body=payload()
    row=body['bars'][DAILY_UNIVERSE[0]][0]
    if bad=='missing_field': del row['o']
    elif bad=='unknown_field': row['future_field']=1
    else: row['o']=float('inf') if bad=='nonfinite' else 'REPLACE_NUMBER'
    encoded=json.dumps(body).replace('"REPLACE_NUMBER"','1e-10000' if bad=='underflow' else '1e10000').encode()
    client,_=adapter(response(body=encoded))
    with pytest.raises(AlpacaDataError): client.fetch(request())


@pytest.mark.parametrize('status', [301,302,307,400,401,403,429,500,503])
def test_api_errors_do_not_retry_or_leak_response(status):
    client,transport=adapter(response(status=status,body=SECRET.encode()))
    with pytest.raises(AlpacaDataError) as caught: client.fetch(request())
    assert caught.value.code=='HTTP_STATUS' and caught.value.http_status==status
    assert SECRET not in str(caught.value) and len(transport.calls)==1


@pytest.mark.parametrize('change', [dict(content_type='text/html'),dict(content_encoding='gzip'),
    dict(body=b'x'*1000)])
def test_http_validation_and_response_bound(change):
    client,transport=adapter(response(**change),limits=TransportLimits(max_response_bytes=999))
    with pytest.raises(AlpacaDataError): client.fetch(request())
    assert len(transport.calls)==1


@pytest.mark.parametrize('error', [RuntimeError(SECRET),TimeoutError(SECRET),AlpacaDataError(SECRET)])
def test_native_and_typed_failures_never_expose_credentials(error,capsys,caplog):
    client,_=adapter(error)
    with pytest.raises(AlpacaDataError) as caught: client.fetch(request())
    rendered=''.join(traceback.format_exception(caught.value))
    assert SECRET not in rendered and KEY not in rendered
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    captured=capsys.readouterr()
    assert captured.out==captured.err=='' and caplog.text==''


def test_credentials_redaction_no_pickle_and_echo_refusal():
    credentials=AlpacaCredentials(KEY,SECRET)
    assert KEY not in repr(credentials) and SECRET not in str(credentials)
    with pytest.raises(TypeError): pickle.dumps(credentials)
    body=payload(); body['bars'][DAILY_UNIVERSE[0]][0]['extra']=SECRET
    client,_=adapter(response(body))
    with pytest.raises(AlpacaDataError,match='CREDENTIAL_ECHO'): client.fetch(request())


def test_environment_pair_precedence_without_file_read(tmp_path):
    assert repr(load_credentials(environ=dict(zip(module.KEY_NAMES,(KEY,SECRET))),env_file=tmp_path/'missing'))=='AlpacaCredentials(<redacted>)'
    with pytest.raises(AlpacaDataError,match='INCOMPLETE_ENVIRONMENT'):
        load_credentials(environ={module.KEY_NAMES[0]:KEY},env_file=tmp_path/'missing')


def test_dotenv_quoted_values_no_interpolation_or_global_mutation(tmp_path,monkeypatch):
    path=tmp_path/'invented.env'
    path.write_text('OTHER=ignored\nALPACA_API_KEY="'+KEY+'"\nALPACA_API_SECRET=\''+SECRET+'\'\n')
    monkeypatch.delenv('ALPACA_API_KEY',raising=False)
    credentials=load_credentials(environ={},env_file=path)
    assert credentials._key==KEY and credentials._secret==SECRET
    assert 'ALPACA_API_KEY' not in module.os.environ


@pytest.mark.parametrize('text', ['ALPACA_API_KEY=\nALPACA_API_SECRET=x',
    'ALPACA_API_KEY=x\nALPACA_API_KEY=y\nALPACA_API_SECRET=z',
    'ALPACA_API_KEY="unterminated', 'OTHER=present'])
def test_bad_dotenv_safe_error(tmp_path,text,capsys):
    path=tmp_path/'invented.env';path.write_text(text)
    with pytest.raises(AlpacaDataError): load_credentials(environ={},env_file=path)
    captured=capsys.readouterr();assert captured.out==captured.err==''


class FakeResponse:
    status=200
    def __init__(self,body): self.body=body
    def read(self,n): chunk,self.body=self.body[:n],self.body[n:];return chunk
    def getheader(self,name,default=''): return {'Content-Type':'application/json','Content-Encoding':'identity'}.get(name,default)


class FakeConnection:
    sock=None
    def __init__(self,response): self.response=response;self.calls=[];self.closed=False
    def request(self,method,path,headers):
        assert set(headers)=={'APCA-API-KEY-ID','APCA-API-SECRET-KEY','Accept'}
        self.calls.append((method,path))
    def getresponse(self): return self.response
    def close(self): self.closed=True


def test_real_http_routine_one_fixed_host_get_and_close():
    connection=FakeConnection(FakeResponse(response().body))
    def factory(host,port,**kwargs):
        assert (host,port)==('data.alpaca.markets',443) and kwargs['timeout']==10
        return connection
    result=_http_once(request(),AlpacaCredentials(KEY,SECRET),TransportLimits(),connection_factory=factory)
    assert result.status==200 and len(connection.calls)==1 and connection.calls[0][0]=='GET' and connection.closed
    assert connection.calls[0][1].startswith('/v2/stocks/bars?')


def test_http_stream_size_timeout_and_redirect_never_followed():
    for mode in ('size','timeout','redirect'):
        connection=FakeConnection(FakeResponse(b'x'*100))
        if mode=='redirect': connection.response.status=302
        kwargs=dict(connection_factory=lambda *a,**k:connection)
        if mode=='timeout':
            ticks=iter([0,31]);kwargs['monotonic']=lambda:next(ticks)
        if mode=='redirect':
            assert _http_once(request(),AlpacaCredentials(KEY,SECRET),TransportLimits(),**kwargs).status==302
        else:
            with pytest.raises(AlpacaDataError):
                _http_once(request(),AlpacaCredentials(KEY,SECRET),TransportLimits(max_response_bytes=10),**kwargs)
        assert len(connection.calls)==1 and connection.closed


def test_worker_transport_no_credentials_in_command_and_no_retry(monkeypatch):
    calls=[]
    class Process:
        returncode=0
        def __init__(self,command,**kwargs):
            calls.append(command)
            assert KEY not in repr(command) and SECRET not in repr(command)
            assert '-B' in command and kwargs['stderr']==subprocess.DEVNULL
        def communicate(self,message=None,timeout=None):
            data=json.loads(message)
            assert data['credentials']==[KEY,SECRET] and timeout==30
            return (json.dumps(dict(status=200,body=module.base64.b64encode(response().body).decode(),
                content_type='application/json',content_encoding='identity')).encode(),None)
        def poll(self):return 0
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    assert SingleGETTransport().get(request(),AlpacaCredentials(KEY,SECRET),TransportLimits()).status==200
    assert len(calls)==1


def test_worker_overall_deadline_kills_without_retry(monkeypatch):
    instances=[]
    class Process:
        returncode=None
        def __init__(self,*a,**k):self.killed=False;instances.append(self)
        def communicate(self,message=None,timeout=None):
            if not self.killed: raise subprocess.TimeoutExpired('worker',timeout)
            return b'',None
        def poll(self):return 0 if self.killed else None
        def kill(self):self.killed=True
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    with pytest.raises(AlpacaDataError,match='TIMEOUT'):
        SingleGETTransport().get(request(),AlpacaCredentials(KEY,SECRET),TransportLimits())
    assert len(instances)==1 and instances[0].killed


def test_import_and_construction_never_load_credentials_or_request(monkeypatch):
    def forbidden(*a,**k): pytest.fail('Unexpected I/O')
    monkeypatch.setattr(module,'load_credentials',forbidden)
    monkeypatch.setattr(module.subprocess,'Popen',forbidden)
    assert isinstance(AlpacaMarketDataAdapter(),AlpacaMarketDataAdapter)


def test_clock_reversal_and_result_trust_literals():
    client,_=adapter();ticks=iter([NOW,NOW-timedelta(seconds=1)]);client.clock=lambda:next(ticks)
    with pytest.raises(AlpacaDataError,match='CLOCK_MOVED_BACKWARDS'):client.fetch(request())
    client,_=adapter();result=client.fetch(request())
    for change in ({'status':'VERIFIED'},{'scope':'real'},{'provider_final':True}):
        with pytest.raises(ValueError): AlpacaDailyBatch.model_validate(result.model_dump(mode='json')|change)


@pytest.mark.parametrize('permitted', ['AAPL', (), ('AAPL','AAPL'), ('AAPL/evil',)])
def test_permitted_universe_is_explicit_and_unambiguous(permitted):
    with pytest.raises(AlpacaDataError): AlpacaMarketDataAdapter(permitted_symbols=permitted)


@pytest.mark.parametrize('day,stamp', [('2026-03-09','2026-03-09T04:00:00Z'),
    ('2026-11-02','2026-11-02T05:00:00Z')])
def test_daily_timestamp_alignment_across_dst(day,stamp):
    body=payload(('AAPL',));body['bars']['AAPL']=body['bars']['AAPL'][:1];body['bars']['AAPL'][0]['t']=stamp
    client,_=adapter(response(body))
    result=client.fetch(request(symbols=('AAPL',),start=day,end=day,expected_session_dates=(day,)))
    assert result.observations[0].bars[0].session_date==date.fromisoformat(day)


def test_response_limit_and_weekend_labels_fail():
    client,_=adapter()
    with pytest.raises(AlpacaDataError,match='RESPONSE_EXCEEDS_REQUEST_LIMIT'):
        client.fetch(request(limit=29))
    body=payload()
    for rows in body['bars'].values(): rows[0]['t']='2026-10-25T04:00:00Z'
    client,_=adapter(response(body))
    with pytest.raises(AlpacaDataError,match='BAR_DATE_OR_RANGE'):
        client.fetch(request(start='2026-10-24',expected_session_dates=None))


@pytest.mark.parametrize('failure', [False,True])
def test_worker_ipc_is_private_and_errors_are_sanitized(monkeypatch,failure):
    class Input:
        buffer=io.BytesIO(json.dumps(dict(request=request().model_dump(mode='json'),
            limits=TransportLimits().model_dump(mode='json'),credentials=[KEY,SECRET])).encode())
    output=io.StringIO()
    monkeypatch.setattr(module.sys,'stdin',Input())
    monkeypatch.setattr(module.sys,'stdout',output)
    def fake(*args):
        if failure: raise OSError(SECRET)
        return response()
    monkeypatch.setattr(module,'_http_once',fake)
    module._worker()
    value=json.loads(output.getvalue())
    assert KEY not in output.getvalue() and SECRET not in output.getvalue()
    if failure: assert value=={'error':'TRANSPORT_FAILURE'}
    else: assert value['status']==200


@pytest.mark.parametrize('mode', ['bad_json','timeout_reply','oversize'])
def test_bad_worker_reply_is_sanitized_without_retry(monkeypatch,mode):
    calls=[]
    class Process:
        returncode=0
        def __init__(self,*a,**k):calls.append(True)
        def communicate(self,*a,**k):
            output = SECRET.encode() if mode=='bad_json' else json.dumps({'error':'TIMEOUT'}).encode()
            if mode=='oversize': output=b'x'*10000
            return output,None
        def poll(self):return 0
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    with pytest.raises(AlpacaDataError) as caught:
        SingleGETTransport().get(request(),AlpacaCredentials(KEY,SECRET),TransportLimits(max_response_bytes=1))
    assert SECRET not in ''.join(traceback.format_exception(caught.value)) and calls==[True]
