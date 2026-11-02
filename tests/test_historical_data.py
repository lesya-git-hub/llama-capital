
import pandas as pd
import pytest

from tools.historical_data import (
    normalize_yfinance_data,
    validate_ohlcv_data,
    download_historical_data,
    extract_ohlcv_arrays,
)


def test_normalize_multiindex_columns():
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "MSFT"),
            ("High", "MSFT"),
            ("Low", "MSFT"),
            ("Close", "MSFT"),
            ("Volume", "MSFT"),
            ("Adj Close", "MSFT"),
        ]
    )

    data = pd.DataFrame(
        [[100, 110, 90, 105, 1000, 104]],
        columns=columns,
        index=pd.to_datetime(["2026-01-05"]),
    )

    result = normalize_yfinance_data(data, "MSFT")

    assert not isinstance(result.columns, pd.MultiIndex)
    assert result["Close"].iloc[0] == 105
    assert result["Adj Close"].iloc[0] == 104


def test_normalize_flat_columns():
    data = pd.DataFrame(
        {
            "Open": [100],
            "High": [110],
            "Low": [90],
            "Close": [105],
            "Volume": [1000],
        }
    )

    result = normalize_yfinance_data(data, "MSFT")

    assert list(result.columns) == list(data.columns)


def test_normalize_rejects_empty_data():
    with pytest.raises(ValueError, match="empty"):
        normalize_yfinance_data(pd.DataFrame(), "MSFT")


def test_normalize_rejects_missing_columns():
    data = pd.DataFrame(
        {
            "Open": [100],
            "Close": [105],
        }
    )

    with pytest.raises(ValueError, match="Missing required"):
        normalize_yfinance_data(data, "MSFT")


def test_normalize_rejects_wrong_ticker():
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
        ]
    )

    data = pd.DataFrame(
        [[100, 110, 90, 105, 1000]],
        columns=columns,
    )

    with pytest.raises(ValueError, match="not found"):
        normalize_yfinance_data(data, "MSFT")


def test_normalize_sorts_dates():
    data = pd.DataFrame(
        {
            "Open": [110, 100],
            "High": [115, 105],
            "Low": [105, 95],
            "Close": [112, 102],
            "Volume": [1000, 2000],
        },
        index=pd.to_datetime(
            ["2026-01-06", "2026-01-05"]
        ),
    )

    result = normalize_yfinance_data(data, "MSFT")

    assert result.index.is_monotonic_increasing
    assert result["Open"].tolist() == [100, 110]

@pytest.fixture
def valid_ohlcv():
    return pd.DataFrame(
        {
            "Open": [100.0, 105.0, 110.0],
            "High": [110.0, 115.0, 120.0],
            "Low": [95.0, 100.0, 105.0],
            "Close": [105.0, 110.0, 115.0],
            "Volume": [1000, 1200, 1500],
        },
        index=pd.to_datetime([
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
        ]),
    )


def test_validate_accepts_valid_data(valid_ohlcv):
    assert validate_ohlcv_data(valid_ohlcv) is None


def test_validate_rejects_duplicate_dates(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.index = pd.to_datetime([
        "2026-01-05",
        "2026-01-05",
        "2026-01-07",
    ])

    with pytest.raises(ValueError, match="Duplicate dates"):
        validate_ohlcv_data(data)


def test_validate_rejects_missing_prices(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Close"] = float("nan")

    with pytest.raises(ValueError, match="Missing price"):
        validate_ohlcv_data(data)


def test_validate_rejects_negative_prices(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Open"] = -100

    with pytest.raises(ValueError, match="Invalid price"):
        validate_ohlcv_data(data)


def test_validate_rejects_invalid_high_low(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "High"] = 90

    with pytest.raises(ValueError, match="Invalid OHLC"):
        validate_ohlcv_data(data)


def test_validate_rejects_negative_volume(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Volume"] = -100

    with pytest.raises(ValueError, match="Invalid volume"):
        validate_ohlcv_data(data)


def test_validate_rejects_missing_volume(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Volume"] = float("nan")

    with pytest.raises(ValueError, match="Missing volume"):
        validate_ohlcv_data(data)


def test_validate_rejects_unsorted_dates(valid_ohlcv):
    data = valid_ohlcv.iloc[::-1]

    with pytest.raises(ValueError, match="Dates must be sorted"):
        validate_ohlcv_data(data)

def test_normalize_preserves_corporate_actions():
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
            ("Adj Close", "AAPL"),
            ("Dividends", "AAPL"),
            ("Stock Splits", "AAPL"),
        ]
    )

    data = pd.DataFrame(
        [[127.58, 131.0, 126.0, 129.04,
          1000000, 125.06, 0.0, 4.0]],
        columns=columns,
        index=pd.to_datetime(["2020-08-31"]),
    )

    result = normalize_yfinance_data(data, "AAPL")

    assert result["Stock Splits"].iloc[0] == 4.0
    assert result["Dividends"].iloc[0] == 0.0
    assert result["Adj Close"].iloc[0] == 125.06
    assert result["Close"].iloc[0] == 129.04

def test_download_historical_data_success(monkeypatch, valid_ohlcv):
    data = valid_ohlcv.copy()
    data["Dividends"] = 0.0
    data["Stock Splits"] = 0.0

    def fake_download(**kwargs):
        assert kwargs["tickers"] == "MSFT"
        assert kwargs["auto_adjust"] is False
        assert kwargs["actions"] is True
        return data

    monkeypatch.setattr(
        "tools.historical_data.yf.download",
        fake_download,
    )

    result = download_historical_data(
        "MSFT",
        "2026-01-01",
        "2026-01-10",
    )

    assert len(result) == 3
    assert "Dividends" in result.columns
    assert "Stock Splits" in result.columns


def test_download_rejects_empty_ticker():
    with pytest.raises(ValueError, match="Ticker"):
        download_historical_data(
            "",
            "2026-01-01",
            "2026-01-10",
        )


def test_download_rejects_invalid_date_range():
    with pytest.raises(ValueError, match="Start date"):
        download_historical_data(
            "MSFT",
            "2026-01-10",
            "2026-01-01",
        )

def test_download_rejects_empty_provider_response(monkeypatch):
    def fake_download(**kwargs):
        return pd.DataFrame()

    monkeypatch.setattr(
        "tools.historical_data.yf.download",
        fake_download,
    )

    with pytest.raises(ValueError, match="empty"):
        download_historical_data(
            "MSFT",
            "2026-01-01",
            "2026-01-10",
        )


def test_download_rejects_corrupted_prices(
    monkeypatch,
    valid_ohlcv,
):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Close"] = -50.0

    def fake_download(**kwargs):
        return data

    monkeypatch.setattr(
        "tools.historical_data.yf.download",
        fake_download,
    )

    with pytest.raises(ValueError, match="Invalid price"):
        download_historical_data(
            "MSFT",
            "2026-01-01",
            "2026-01-10",
        )


def test_download_rejects_duplicate_dates(
    monkeypatch,
    valid_ohlcv,
):
    data = valid_ohlcv.copy()
    data.index = pd.to_datetime([
        "2026-01-05",
        "2026-01-05",
        "2026-01-07",
    ])

    def fake_download(**kwargs):
        return data

    monkeypatch.setattr(
        "tools.historical_data.yf.download",
        fake_download,
    )

    with pytest.raises(ValueError, match="Duplicate dates"):
        download_historical_data(
            "MSFT",
            "2026-01-01",
            "2026-01-10",
        )

def test_download_handles_provider_exception(monkeypatch):
    def fake_download(**kwargs):
        raise ConnectionError("Provider unavailable")

    monkeypatch.setattr(
        "tools.historical_data.yf.download",
        fake_download,
    )

    with pytest.raises(
        RuntimeError,
        match="Failed to download historical data for MSFT",
    ) as exc_info:
        download_historical_data(
            "MSFT",
            "2026-01-01",
            "2026-01-10",
        )

    assert isinstance(
        exc_info.value.__cause__,
        ConnectionError,
    )

def test_extract_ohlcv_arrays(valid_ohlcv):
    result = extract_ohlcv_arrays(valid_ohlcv)

    assert result["opens"] == [100.0, 105.0, 110.0]
    assert result["highs"] == [110.0, 115.0, 120.0]
    assert result["lows"] == [95.0, 100.0, 105.0]
    assert result["closes"] == [105.0, 110.0, 115.0]
    assert result["volumes"] == [1000.0, 1200.0, 1500.0]


def test_extract_ohlcv_arrays_preserves_date_order(valid_ohlcv):
    result = extract_ohlcv_arrays(valid_ohlcv)

    assert len(result["opens"]) == len(valid_ohlcv)
    assert len(result["closes"]) == len(valid_ohlcv)
    assert result["closes"][0] == 105.0
    assert result["closes"][-1] == 115.0


def test_extract_ohlcv_arrays_rejects_invalid_data(valid_ohlcv):
    data = valid_ohlcv.copy()
    data.loc["2026-01-06", "Low"] = -10.0

    with pytest.raises(ValueError, match="Invalid price"):
        extract_ohlcv_arrays(data)
