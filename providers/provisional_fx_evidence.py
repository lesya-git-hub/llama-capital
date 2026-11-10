"""Pure invented-record normalizer; no transport or financial conversion API."""
from datetime import date, datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
import json
import re
from typing import Protocol
from zoneinfo import ZoneInfo

from models.fx_evidence import FXNormalizedRate, FXRecord, FXSeries
from tools.historical_snapshot import input_hash

CONTEXT = Context(prec=80, rounding=ROUND_HALF_EVEN)


class RecordedFXProvider(Protocol):
    def read_recorded(self, reference_date: date) -> FXRecord: ...


def decode(record):
    if sha256(record.body()).hexdigest() != record.receipt.raw_sha256:
        raise ValueError('RAW_HASH_MISMATCH')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def bad(value):
        raise ValueError('NONFINITE_JSON')
    value = json.loads(record.body().decode('utf-8'), object_pairs_hook=unique, parse_constant=bad)
    if type(value) is not dict:
        raise ValueError('OBJECT_REQUIRED')
    return value


def instant(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('EXPLICIT_INSTANT_REQUIRED')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('AWARE_INSTANT_REQUIRED')
    return stamp.astimezone(timezone.utc)


def numeric_fx(record, series):
    record = FXRecord.model_validate(record.model_dump(mode='json'))
    series = FXSeries.model_validate(series.model_dump(mode='json'))
    if record.kind != 'raw':
        raise ValueError('RAW_RATE_REQUIRED')
    r, value = record.receipt, decode(record)
    expected_keys = {'provider_id', 'dataset_id', 'feed', 'release_id', 'base', 'quote', 'direction',
        'units', 'rate_kind', 'reference_date', 'effective_at', 'published_at', 'rate'}
    if set(value) != expected_keys:
        raise ValueError('EXACT_RATE_SCHEMA_REQUIRED')
    direct = (series.base, series.quote, series.direction, series.operation) == ('USD', 'EUR', 'EUR_PER_USD', 'direct')
    reverse = (series.base, series.quote, series.direction, series.operation) == ('EUR', 'USD', 'USD_PER_EUR', 'explicit_reciprocal')
    if not (direct or reverse):
        raise ValueError('PAIR_OR_EXPLICIT_OPERATION_MISMATCH')
    for name in ('provider_id', 'dataset_id', 'feed'):
        if value[name] != getattr(series, name) or value[name] != getattr(r, name):
            raise ValueError('SOURCE_IDENTITY_MISMATCH')
    for name in ('base', 'quote', 'direction', 'units', 'rate_kind'):
        if value[name] != getattr(series, name):
            raise ValueError('PAIR_OR_CONVENTION_MISMATCH')
    if value['release_id'] != r.release_id:
        raise ValueError('WRONG_RELEASE_METADATA')
    lexical = value['rate']
    if not isinstance(lexical, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', lexical):
        raise ValueError('EXPLICIT_DECIMAL_TEXT_REQUIRED')
    rate = Decimal(lexical)
    if not rate.is_finite() or not 0 < rate <= Decimal('1e12') or len(rate.as_tuple().digits) > 36:
        raise ValueError('RATE_BOUNDS')
    if -rate.as_tuple().exponent > min(24, series.source_precision):
        raise ValueError('UNSUPPORTED_RATE_PRECISION')
    day = value['reference_date']
    if not isinstance(day, str) or len(day) != 10 or date.fromisoformat(day).isoformat() != day:
        raise ValueError('PLAIN_REFERENCE_DATE_REQUIRED')
    with localcontext(CONTEXT):
        canonical = rate if direct else Decimal(1) / rate
        text = str(canonical.normalize())
    return value, text


def normalize_fx(record, series, *, series_sha256):
    value, text = numeric_fx(record, series)
    r = record.receipt
    day = value['reference_date']
    if not isinstance(day, str) or len(day) != 10 or date.fromisoformat(day).isoformat() != day:
        raise ValueError('PLAIN_REFERENCE_DATE_REQUIRED')
    effective, publication = instant(value['effective_at']), instant(value['published_at'])
    if publication != r.published_at or effective.astimezone(ZoneInfo(series.timezone)).date().isoformat() != day:
        raise ValueError('TIME_OR_REFERENCE_DATE_MISMATCH')
    if not effective <= publication <= r.acquired_end:
        raise ValueError('EFFECTIVE_PUBLICATION_ACQUISITION_ORDER')
    return FXNormalizedRate(raw_id=r.observation_id, raw_record_sha256=input_hash(record),
        series_sha256=series_sha256, reference_date=day, original_rate_text=value['rate'],
        original_direction=series.direction, operation=series.operation, canonical_rate_text=text,
        effective_at=effective, published_at=publication, acquired_end=r.acquired_end)
