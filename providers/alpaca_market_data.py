"""Explicit single-GET Alpaca research adapter. In memory only; no publication API."""
import base64
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import http.client
import json
import math
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time as clock_time
from typing import Literal, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from dotenv.parser import parse_stream
from pydantic import AwareDatetime, Field, field_validator, model_validator

from models.daily_signals import DAILY_UNIVERSE
from tools.historical_snapshot import FrozenModel

ORIGIN = 'https://data.alpaca.markets'
PATH = '/v2/stocks/bars'
NEW_YORK = ZoneInfo('America/New_York')
KEY_NAMES = ('ALPACA_API_KEY', 'ALPACA_API_SECRET')
ERROR_CODES = frozenset('INVALID_CREDENTIALS INCOMPLETE_ENVIRONMENT_CREDENTIALS INVALID_DOTENV '
    'DUPLICATE_DOTENV_CREDENTIAL CREDENTIAL_LOAD_FAILED TRANSPORT_FAILURE TIMEOUT RESPONSE_TOO_LARGE '
    'HTTP_STATUS INVALID_HTTP_RESPONSE CREDENTIAL_ECHO INVALID_RESPONSE_SCHEMA PAGINATION_NOT_SUPPORTED '
    'SYMBOL_COVERAGE_MISMATCH EMPTY_SYMBOL_BARS INVALID_BAR_SCHEMA INVALID_BAR_TIMESTAMP '
    'BAR_DATE_OR_RANGE_MISMATCH INVALID_TRADE_COUNT DUPLICATE_OR_UNORDERED_DATES MISALIGNED_SYMBOL_DATES '
    'EXPECTED_SESSION_COVERAGE_MISMATCH RESPONSE_EXCEEDS_REQUEST_LIMIT INVALID_PERMITTED_UNIVERSE '
    'SYMBOL_NOT_PERMITTED FUTURE_REQUEST CLOCK_MOVED_BACKWARDS INVALID_RESPONSE_DATA ADAPTER_FAILURE'.split())


class AlpacaDataError(ValueError):
    """Fixed error codes only. No provider bodies, headers or native exceptions."""
    def __init__(self, code, *, http_status=None):
        self.code = code if isinstance(code, str) and code in ERROR_CODES else 'ADAPTER_FAILURE'
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


def _date(value):
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    raise ValueError('Plain YYYY-MM-DD session date required')


def _boundary(value, *, end=False):
    if type(value) is date or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        day = _date(value)
        if end:
            return (datetime.combine(day + timedelta(days=1), time(), NEW_YORK)
                - timedelta(microseconds=1)).astimezone(timezone.utc)
        return datetime.combine(day, time(), NEW_YORK).astimezone(timezone.utc)
    if isinstance(value, str) and 'T' in value:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Explicit aware instant or plain session date required')
    return value.astimezone(timezone.utc)


class DailyBarsRequest(FrozenModel):
    model_config = {**FrozenModel.model_config, 'validate_default': True}
    symbols: tuple[str, ...] = DAILY_UNIVERSE
    start: AwareDatetime
    end: AwareDatetime
    timeframe: Literal['1Day'] = '1Day'
    adjustment: Literal['split'] = 'split'
    feed: Literal['iex'] = 'iex'
    currency: Literal['USD'] = 'USD'
    limit: int = Field(default=100, ge=1, le=10000, strict=True)
    expected_session_dates: tuple[date, ...] | None = Field(default=None, max_length=10000)

    @field_validator('symbols', mode='before')
    @classmethod
    def symbols_valid(cls, value):
        if not isinstance(value, (tuple, list)) or not value or len(value) > 100 or any(
                not isinstance(v, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', v) for v in value) or len(set(value)) != len(value):
            raise ValueError('Distinct explicit uppercase symbols required')
        return value

    @field_validator('start', 'end', mode='before')
    @classmethod
    def instants(cls, value, info):
        return _boundary(value, end=info.field_name == 'end')

    @field_validator('expected_session_dates', mode='before')
    @classmethod
    def expected_dates(cls, value):
        return None if value is None else tuple(_date(d) for d in value)

    @model_validator(mode='after')
    def chronology(self):
        if self.start > self.end:
            raise ValueError('Start follows end')
        days = self.expected_session_dates
        if days is not None and (not days or tuple(sorted(set(days))) != days or any(
                not self.start <= datetime.combine(d, time(), NEW_YORK).astimezone(timezone.utc) <= self.end for d in days)):
            raise ValueError('Expected dates must be ordered, distinct and within request')
        return self

    def query(self):
        return dict(symbols=','.join(self.symbols), timeframe=self.timeframe,
            start=self.start.isoformat().replace('+00:00', 'Z'), end=self.end.isoformat().replace('+00:00', 'Z'),
            adjustment=self.adjustment, feed=self.feed, currency=self.currency, limit=self.limit, sort='asc')

    @property
    def url(self):
        return ORIGIN + PATH + '?' + urlencode(self.query())


class TransportLimits(FrozenModel):
    socket_timeout_seconds: int = Field(default=10, ge=1, le=60, strict=True)
    overall_timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    max_response_bytes: int = Field(default=256 * 1024, ge=1, le=8 * 1024 * 1024, strict=True)


class AlpacaCredentials:
    __slots__ = ('_key', '_secret')

    def __init__(self, key, secret):
        if not all(isinstance(v, str) and 0 < len(v) <= 512 and v.isascii()
                and all(33 <= ord(c) <= 126 for c in v) for v in (key, secret)):
            raise AlpacaDataError('INVALID_CREDENTIALS')
        self._key, self._secret = key, secret

    def __repr__(self):
        return 'AlpacaCredentials(<redacted>)'

    def __reduce_ex__(self, protocol):
        raise TypeError('Credentials cannot be serialized')


def load_credentials(*, environ=None, env_file='.env'):
    """Complete environment pair takes precedence; never combine partial pairs."""
    error, values = None, None
    try:
        env = os.environ if environ is None else environ
        present = [name in env for name in KEY_NAMES]
        if any(present):
            if not all(present):
                error = 'INCOMPLETE_ENVIRONMENT_CREDENTIALS'
            else:
                values = tuple(env[name] for name in KEY_NAMES)
        else:
            selected = {}
            with open(env_file, encoding='utf-8-sig') as stream:
                for binding in parse_stream(stream):
                    if binding.error:
                        error = 'INVALID_DOTENV'
                        break
                    if binding.key in KEY_NAMES:
                        if binding.key in selected:
                            error = 'DUPLICATE_DOTENV_CREDENTIAL'
                            break
                        selected[binding.key] = binding.value
            if error is None:
                values = tuple(selected.get(name) for name in KEY_NAMES)
    except Exception:
        error = 'CREDENTIAL_LOAD_FAILED'
    if error is not None:
        raise AlpacaDataError(error)
    return AlpacaCredentials(*values)


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes = field(default=b'', repr=False)
    content_type: str = 'application/json'
    content_encoding: str = 'identity'


class AlpacaTransport(Protocol):
    def get(self, request: DailyBarsRequest, credentials: AlpacaCredentials,
            limits: TransportLimits) -> HTTPResponse: ...


def _http_once(request, credentials, limits, *, connection_factory=None, monotonic=None):
    """One fixed-origin GET; called in a deadline-bounded worker by default."""
    factory = connection_factory or http.client.HTTPSConnection
    tick = monotonic or clock_time.monotonic
    started, connection = tick(), None
    try:
        connection = factory('data.alpaca.markets', 443, timeout=limits.socket_timeout_seconds,
            context=ssl.create_default_context())
        connection.request('GET', PATH + '?' + urlencode(request.query()), headers={
            'APCA-API-KEY-ID': credentials._key, 'APCA-API-SECRET-KEY': credentials._secret,
            'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            return HTTPResponse(response.status)  # Never retain/parse provider error bodies.
        payload = bytearray()
        while True:
            remaining = limits.overall_timeout_seconds - (tick() - started)
            if remaining <= 0:
                raise AlpacaDataError('TIMEOUT')
            if connection.sock is not None:
                connection.sock.settimeout(min(limits.socket_timeout_seconds, remaining))
            chunk = response.read(min(8192, limits.max_response_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > limits.max_response_bytes:
                raise AlpacaDataError('RESPONSE_TOO_LARGE')
        return HTTPResponse(response.status, bytes(payload), response.getheader('Content-Type', ''),
            response.getheader('Content-Encoding', 'identity'))
    finally:
        if connection is not None:
            connection.close()


def _worker():
    """Private IPC; response bytes travel only in memory, never to a terminal/file."""
    reply = {'error': 'TRANSPORT_FAILURE'}
    try:
        message = json.loads(sys.stdin.buffer.read(128 * 1024))
        request = DailyBarsRequest.model_validate(message['request'])
        limits = TransportLimits.model_validate(message['limits'])
        credentials = AlpacaCredentials(*message['credentials'])
        response = _http_once(request, credentials, limits)
        reply = dict(status=response.status, body=base64.b64encode(response.body).decode(),
            content_type=response.content_type, content_encoding=response.content_encoding)
    except AlpacaDataError as exc:
        reply = {'error': exc.code}
    except TimeoutError:
        reply = {'error': 'TIMEOUT'}
    except BaseException:
        pass  # Do not emit native exceptions, headers or configuration.
    sys.stdout.write(json.dumps(reply))


class SingleGETTransport:
    """No retry/redirect/proxy logic. A worker deadline also bounds blocking DNS."""
    def get(self, request, credentials, limits):
        message = json.dumps(dict(request=request.model_dump(mode='json'), limits=limits.model_dump(mode='json'),
            credentials=[credentials._key, credentials._secret])).encode()
        root = str(Path(__file__).resolve().parents[1])
        command = [sys.executable, '-B', '-c',
            'import sys; sys.path.insert(0,sys.argv[1]); from providers.alpaca_market_data import _worker; _worker()', root]
        process, error, response = None, 'TRANSPORT_FAILURE', None
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output, _ = process.communicate(message, timeout=limits.overall_timeout_seconds)
            if process.returncode != 0 or len(output) > limits.max_response_bytes * 2 + 8192:
                raise ValueError()
            value = json.loads(output)
            if set(value) == {'error'} and value['error'] in ('TIMEOUT', 'RESPONSE_TOO_LARGE', 'TRANSPORT_FAILURE'):
                error = value['error']
            elif set(value) == {'status', 'body', 'content_type', 'content_encoding'}:
                response = HTTPResponse(value['status'], base64.b64decode(value['body'], validate=True),
                    value['content_type'], value['content_encoding'])
        except subprocess.TimeoutExpired:
            error = 'TIMEOUT'  # May already have reached provider; never retry.
        except Exception:
            pass
        finally:
            try:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate()
            except Exception:
                response, error = None, 'TRANSPORT_FAILURE'
        if response is None:
            raise AlpacaDataError(error)
        return response


class AlpacaDailyBar(FrozenModel):
    timestamp: AwareDatetime
    session_date: date
    open: float = Field(gt=0, strict=True)
    high: float = Field(gt=0, strict=True)
    low: float = Field(gt=0, strict=True)
    close: float = Field(gt=0, strict=True)
    volume: float = Field(ge=0, strict=True)
    trade_count: int | None = Field(default=None, ge=0, strict=True)
    vwap: float | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def relationships(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Invalid OHLC relationship')
        return self


class AlpacaSymbolBars(FrozenModel):
    symbol: str
    bars: tuple[AlpacaDailyBar, ...] = Field(repr=False)


class AlpacaDailyBatch(FrozenModel):
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    scope: Literal['unverified'] = 'unverified'
    provider: Literal['alpaca'] = 'alpaca'
    source_endpoint: Literal['https://data.alpaca.markets/v2/stocks/bars'] = ORIGIN + PATH
    request: DailyBarsRequest
    observations: tuple[AlpacaSymbolBars, ...] = Field(repr=False)
    acquired_start: AwareDatetime
    acquired_end: AwareDatetime
    receipt_clock: Literal['local_unattested'] = 'local_unattested'
    publication_time: None = None
    provider_final: Literal[False] = False
    pagination_complete: Literal[True] = True
    calendar_verified: Literal[False] = False
    session_coverage: Literal['CALLER_EXPECTATIONS_MATCHED', 'UNVERIFIED']
    adjustment_claim: Literal['request_accepted_not_independently_verified'] = 'request_accepted_not_independently_verified'
    corporate_action_fields: Literal['not_supplied'] = 'not_supplied'


def _unique(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError()
        value[name] = item
    return value


def _number(value, *, positive=True):
    if type(value) not in (int, Decimal) or isinstance(value, Decimal) and not value.is_finite():
        raise ValueError()
    result = float(value)
    if not math.isfinite(result) or value != 0 and result == 0 or (result <= 0 if positive else result < 0):
        raise ValueError()
    return result


def _parse(response, request, credentials):
    if type(response.status) is not int or response.status != 200:
        raise AlpacaDataError('HTTP_STATUS', http_status=response.status if type(response.status) is int else None)
    if (type(response.body) is not bytes or response.content_type.split(';')[0].strip().lower() != 'application/json'
            or response.content_encoding.lower() not in ('identity', '')):
        raise AlpacaDataError('INVALID_HTTP_RESPONSE')
    if any(v.encode() in response.body for v in (credentials._key, credentials._secret)):
        raise AlpacaDataError('CREDENTIAL_ECHO')
    def invalid(value):
        raise ValueError()
    value = json.loads(response.body.decode('utf-8'), parse_float=Decimal,
        parse_constant=invalid, object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != {'bars', 'next_page_token'} or not isinstance(value['bars'], dict):
        raise AlpacaDataError('INVALID_RESPONSE_SCHEMA')
    if value['next_page_token'] is not None:
        raise AlpacaDataError('PAGINATION_NOT_SUPPORTED')
    grouped = value['bars']
    if set(grouped) != set(request.symbols):
        raise AlpacaDataError('SYMBOL_COVERAGE_MISMATCH')
    observations, shared_dates, total = [], None, 0
    for symbol in request.symbols:
        rows = grouped[symbol]
        if not isinstance(rows, list) or not rows:
            raise AlpacaDataError('EMPTY_SYMBOL_BARS')
        bars, dates = [], []
        for row in rows:
            if not isinstance(row, dict) or not {'t', 'o', 'h', 'l', 'c', 'v'} <= set(row) <= {'t', 'o', 'h', 'l', 'c', 'v', 'n', 'vw'}:
                raise AlpacaDataError('INVALID_BAR_SCHEMA')
            stamp = row['t']
            if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', stamp):
                raise AlpacaDataError('INVALID_BAR_TIMESTAMP')
            instant = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc)
            local = instant.astimezone(NEW_YORK)
            if local.timetz().replace(tzinfo=None) != time() or local.weekday() >= 5 or not request.start <= instant <= request.end:
                raise AlpacaDataError('BAR_DATE_OR_RANGE_MISMATCH')
            dates.append(local.date())
            if 'n' in row and (type(row['n']) is not int or row['n'] < 0):
                raise AlpacaDataError('INVALID_TRADE_COUNT')
            bars.append(AlpacaDailyBar(timestamp=instant, session_date=local.date(),
                open=_number(row['o']), high=_number(row['h']), low=_number(row['l']), close=_number(row['c']),
                volume=_number(row['v'], positive=False), trade_count=row.get('n'),
                vwap=_number(row['vw']) if 'vw' in row else None))
        if tuple(sorted(set(dates))) != tuple(dates):
            raise AlpacaDataError('DUPLICATE_OR_UNORDERED_DATES')
        if shared_dates is not None and dates != shared_dates:
            raise AlpacaDataError('MISALIGNED_SYMBOL_DATES')
        if request.expected_session_dates is not None and tuple(dates) != request.expected_session_dates:
            raise AlpacaDataError('EXPECTED_SESSION_COVERAGE_MISMATCH')
        shared_dates = dates
        total += len(bars)
        observations.append(AlpacaSymbolBars(symbol=symbol, bars=tuple(bars)))
    if total > request.limit:
        raise AlpacaDataError('RESPONSE_EXCEEDS_REQUEST_LIMIT')
    return tuple(observations)


class AlpacaMarketDataAdapter:
    def __init__(self, *, transport=None, credentials=None, limits=TransportLimits(),
                 permitted_symbols=DAILY_UNIVERSE, clock=None):
        self.transport = transport if transport is not None else SingleGETTransport()
        self.credentials = credentials
        self.limits = TransportLimits.model_validate(limits.model_dump(mode='json'))
        if not isinstance(permitted_symbols, (tuple, list)) or not permitted_symbols or any(
                not isinstance(s, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', s) for s in permitted_symbols) or len(set(permitted_symbols)) != len(permitted_symbols):
            raise AlpacaDataError('INVALID_PERMITTED_UNIVERSE')
        self.permitted_symbols = frozenset(permitted_symbols)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, request):
        """One explicit fetch, no automatic network activity at import/construction."""
        result, error, http_status = None, 'ADAPTER_FAILURE', None
        try:
            request = DailyBarsRequest.model_validate(request.model_dump(mode='json'))
            if not set(request.symbols) <= self.permitted_symbols:
                raise AlpacaDataError('SYMBOL_NOT_PERMITTED')
            credentials = self.credentials if self.credentials is not None else load_credentials()
            if not isinstance(credentials, AlpacaCredentials):
                raise AlpacaDataError('INVALID_CREDENTIALS')
            start = _boundary(self.clock())
            if request.end > start:
                raise AlpacaDataError('FUTURE_REQUEST')
            response = self.transport.get(request, credentials, self.limits)
            if not isinstance(response, HTTPResponse):
                raise AlpacaDataError('INVALID_HTTP_RESPONSE')
            if len(response.body) > self.limits.max_response_bytes:
                raise AlpacaDataError('RESPONSE_TOO_LARGE')
            observations = _parse(response, request, credentials)
            end = _boundary(self.clock())
            if end < start:
                raise AlpacaDataError('CLOCK_MOVED_BACKWARDS')
            result = AlpacaDailyBatch(request=request, observations=observations, acquired_start=start,
                acquired_end=end, session_coverage='CALLER_EXPECTATIONS_MATCHED' if request.expected_session_dates else 'UNVERIFIED')
        except AlpacaDataError as exc:
            error, http_status = exc.code, exc.http_status
        except TimeoutError:
            error = 'TIMEOUT'
        except (ValueError, TypeError, KeyError):
            error = 'INVALID_RESPONSE_DATA'
        except Exception:
            pass  # Never expose provider content or credential-bearing native errors.
        if result is None:
            # Raise outside handlers so traceback/context cannot include native messages.
            raise AlpacaDataError(error, http_status=http_status)
        return result
