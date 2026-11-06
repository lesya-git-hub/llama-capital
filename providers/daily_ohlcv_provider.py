"""Explicit OHLCV fetch interface and optional Yahoo adapter; no scheduled work."""

from datetime import datetime, timedelta, timezone
from typing import Protocol

import pandas as pd

from models.daily_signals import BarAvailability, DAILY_UNIVERSE, ObservedTicker, Session
from tools.historical_data import download_historical_data, validate_ohlcv_data
from tools.historical_snapshot import Candle, TickerSnapshot


class DailyOHLCVProvider(Protocol):
    def fetch_daily(self, ticker: str, sessions: tuple[Session, ...]) -> ObservedTicker:
        """Return candles and conservative availability/finality evidence."""
        ...


class YahooDailyOHLCVProvider:
    """Reuse historical OHLCV loading only on an explicit fetch call.

    Availability is fetch/verification completion, never retrospectively assumed
    to be the close time. Yahoo exposes no finality flag: rows remain provisional
    unless an explicit named verifier attests finality. Time alone is insufficient.
    The adapter's split-adjusted basis declaration follows the existing loader.
    """

    def __init__(self, *, finality_verifier=None, finality_source: str | None = None):
        if finality_verifier is not None and (
            not callable(finality_verifier) or not isinstance(finality_source, str) or not finality_source.strip()
        ):
            raise ValueError('A callable finality verifier requires a named evidence source')
        self._verifier = finality_verifier
        self._finality_source = finality_source or 'unverified:yfinance has no candle-finality flag'

    def fetch_daily(self, ticker: str, sessions: tuple[Session, ...]) -> ObservedTicker:
        if ticker not in DAILY_UNIVERSE or not sessions:
            raise ValueError('Known six-stock ticker and completed sessions required')
        if any(s.closes_at > datetime.now(timezone.utc) for s in sessions):
            raise ValueError('Cannot fetch unfinished sessions as final candles')
        data = download_historical_data(
            ticker, sessions[0].date.isoformat(), (sessions[-1].date + timedelta(days=1)).isoformat(),
        )
        validate_ohlcv_data(data)
        if any(name not in data.columns for name in ('Dividends', 'Stock Splits')):
            raise ValueError('Explicit corporate-action columns required')
        if any(stamp != stamp.normalize() for stamp in data.index):
            raise ValueError('Provider daily index must contain midnight session labels')
        bars = []
        for stamp, row in data.iterrows():
            if pd.isna(row['Dividends']) or pd.isna(row['Stock Splits']):
                raise ValueError('Missing corporate-action values')
            ratio = float(row['Stock Splits'])
            bars.append(Candle(
                date=stamp.date(), open=float(row['Open']), high=float(row['High']),
                low=float(row['Low']), close=float(row['Close']), volume=float(row['Volume']),
                dividend=float(row['Dividends']), split_ratio=1.0 if ratio == 0 else ratio,
            ))
        snapshot = TickerSnapshot(
            ticker=ticker, currency='USD', source='yfinance:historical_data-v1', calendar='US_EQUITIES',
            price_adjustment='split_adjusted', volume_adjustment='split_adjusted',
            dividend_convention='recorded_not_applied', split_convention='events_recorded_prices_adjusted',
            bars=tuple(bars),
        )
        finality = tuple(self._verifier(ticker, b) if self._verifier is not None else False for b in bars)
        fetched_at = datetime.now(timezone.utc)
        return ObservedTicker(
            snapshot=snapshot, finality_source=self._finality_source, fetched_at=fetched_at,
            availability=tuple(BarAvailability(date=b.date, available_at=fetched_at, final=final)
                               for b, final in zip(bars, finality)),
        )
