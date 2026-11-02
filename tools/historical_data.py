
"""Historical market data loading and normalization."""

import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = (
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
)


def normalize_yfinance_data(
    data: pd.DataFrame,
    ticker: str,
) -> pd.DataFrame:
    """Normalize single-ticker Yahoo Finance data."""

    if data.empty:
        raise ValueError("Historical data is empty")

    result = data.copy()

    if isinstance(result.columns, pd.MultiIndex):
        tickers = result.columns.get_level_values(1).unique()

        if ticker not in tickers:
            raise ValueError(f"Ticker {ticker} not found")

        result = result.xs(
            ticker,
            axis=1,
            level=1,
        )

    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in result.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}"
        )

    return result.sort_index()

def validate_ohlcv_data(data: pd.DataFrame) -> None:
    """Validate historical OHLCV data.

    Raises ValueError if invalid data is detected.
    """

    if data.empty:
        raise ValueError("Historical data is empty")

    missing_columns = [
        col for col in REQUIRED_COLUMNS
        if col not in data.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Index must contain dates")

    if data.index.hasnans:
        raise ValueError("Missing dates detected")

    if data.index.has_duplicates:
        raise ValueError("Duplicate dates detected")

    if not data.index.is_monotonic_increasing:
        raise ValueError("Dates must be sorted")

    prices = data[["Open", "High", "Low", "Close"]]

    if prices.isna().any().any():
        raise ValueError("Missing price values detected")

    if not prices.map(
        lambda value: pd.notna(value)
        and isinstance(value, (int, float))
        and 0 < value < float("inf")
    ).all().all():
        raise ValueError("Invalid price values detected")

    if (
        (data["High"] < data["Low"]).any()
        or (data["High"] < data["Open"]).any()
        or (data["High"] < data["Close"]).any()
        or (data["Low"] > data["Open"]).any()
        or (data["Low"] > data["Close"]).any()
    ):
        raise ValueError("Invalid OHLC relationships detected")

    if data["Volume"].isna().any():
        raise ValueError("Missing volume values detected")

    if not data["Volume"].map(
        lambda value: pd.notna(value)
        and isinstance(value, (int, float))
        and 0 <= value < float("inf")
    ).all():
        raise ValueError("Invalid volume values detected")

def download_historical_data(
    ticker: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Download and validate daily historical OHLCV data.

    Uses split-adjusted Yahoo Finance prices.
    Preserves dividends and stock-split events.
    End date is exclusive.
    """
    if not ticker or not ticker.strip():
        raise ValueError("Ticker must not be empty")

    if pd.Timestamp(start) >= pd.Timestamp(end):
        raise ValueError("Start date must precede end date")

    
    try:
        raw = yf.download(
            tickers=ticker,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to download historical data for {ticker}"
        ) from exc


    data = normalize_yfinance_data(raw, ticker)

    validate_ohlcv_data(data)

    return data

def extract_ohlcv_arrays(
    data: pd.DataFrame,
) -> dict[str, list[float]]:
    """Extract validated OHLCV arrays for quantitative analysis."""

    validate_ohlcv_data(data)

    return {
        "opens": data["Open"].astype(float).tolist(),
        "highs": data["High"].astype(float).tolist(),
        "lows": data["Low"].astype(float).tolist(),
        "closes": data["Close"].astype(float).tolist(),
        "volumes": data["Volume"].astype(float).tolist(),
    }
