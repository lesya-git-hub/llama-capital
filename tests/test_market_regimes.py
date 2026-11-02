from tools.market_regimes import filter_entries_by_regime
import pytest
from tools.market_regimes import (
    MarketRegime,
    classify_market_regime,
    generate_historical_regimes,
)


def classify_closes(closes, volatility_threshold=0.05):
    """Create valid synthetic OHLC data for testing."""
    highs = [price + 1.0 for price in closes]
    lows = [price - 1.0 for price in closes]

    return classify_market_regime(
        highs=highs,
        lows=lows,
        closes=closes,
        volatility_threshold=volatility_threshold,
    )


def test_bull_market():
    closes = [100.0 + i for i in range(200)]

    assert classify_closes(closes) == MarketRegime.BULL


def test_bear_market():
    closes = [300.0 - i for i in range(200)]

    assert classify_closes(closes) == MarketRegime.BEAR


def test_sideways_market():
    closes = [100.0] * 200

    assert classify_closes(closes) == MarketRegime.SIDEWAYS


def test_high_volatility_takes_priority():
    closes = [100.0 + i for i in range(200)]
    highs = [price + 15.0 for price in closes]
    lows = [price - 15.0 for price in closes]

    result = classify_market_regime(
        highs=highs,
        lows=lows,
        closes=closes,
    )

    assert result == MarketRegime.HIGH_VOLATILITY


def test_insufficient_history():
    with pytest.raises(ValueError, match="200 sessions"):
        classify_closes([100.0] * 199)


def test_mismatched_lengths():
    with pytest.raises(ValueError, match="OHLC lengths"):
        classify_market_regime(
            highs=[101.0] * 200,
            lows=[99.0] * 199,
            closes=[100.0] * 200,
        )


@pytest.mark.parametrize(
    "threshold",
    [0.0, -0.01, float("nan"), float("inf")],
)
def test_invalid_volatility_threshold(threshold):
    with pytest.raises(ValueError, match="volatility threshold"):
        classify_closes(
            [100.0] * 200,
            volatility_threshold=threshold,
        )

def test_historical_regimes_warmup():
    closes = [100.0] * 205
    highs = [101.0] * 205
    lows = [99.0] * 205

    regimes = generate_historical_regimes(highs, lows, closes)

    assert len(regimes) == 205
    assert regimes[:199] == [None] * 199
    assert regimes[199:] == [MarketRegime.SIDEWAYS] * 6


def test_historical_regimes_no_future_leakage():
    closes = [100.0 + i * 0.1 for i in range(250)]
    highs = [price + 1.0 for price in closes]
    lows = [price - 1.0 for price in closes]

    original = generate_historical_regimes(
        highs, lows, closes
    )

    modified_closes = closes.copy()
    modified_highs = highs.copy()
    modified_lows = lows.copy()

    # Change only future sessions, from index 220 onward.
    for day in range(220, 250):
        modified_closes[day] = 50.0
        modified_highs[day] = 51.0
        modified_lows[day] = 49.0

    modified = generate_historical_regimes(
        modified_highs,
        modified_lows,
        modified_closes,
    )

    # Earlier classifications must remain identical.
    assert original[:220] == modified[:220]


def test_historical_regimes_reject_mismatched_lengths():
    with pytest.raises(ValueError, match="OHLC lengths"):
        generate_historical_regimes(
            highs=[101.0] * 205,
            lows=[99.0] * 204,
            closes=[100.0] * 205,
        )

def test_bear_filter_preserves_non_bear_signals():
    entries = [True, True, True, False, True]

    regimes = [
        MarketRegime.BULL,
        MarketRegime.BEAR,
        MarketRegime.SIDEWAYS,
        MarketRegime.BEAR,
        MarketRegime.HIGH_VOLATILITY,
    ]

    filtered = [
        entry and regime != MarketRegime.BEAR
        for entry, regime in zip(entries, regimes)
    ]

    assert filtered == [True, False, True, False, True]

def test_filter_entries_excludes_bear_market():
    entries = [True, True, True, False, True]

    regimes = [
        MarketRegime.BULL,
        MarketRegime.BEAR,
        MarketRegime.SIDEWAYS,
        MarketRegime.BEAR,
        MarketRegime.HIGH_VOLATILITY,
    ]

    result = filter_entries_by_regime(
        entries=entries,
        regimes=regimes,
        excluded_regimes={MarketRegime.BEAR},
    )

    assert result == [True, False, True, False, True]


def test_filter_entries_preserves_warmup():
    entries = [True, True, True]

    regimes = [
        None,
        MarketRegime.BULL,
        MarketRegime.BEAR,
    ]

    result = filter_entries_by_regime(
        entries=entries,
        regimes=regimes,
        excluded_regimes={MarketRegime.BEAR},
    )

    assert result == [True, True, False]


def test_filter_entries_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="lengths must match"):
        filter_entries_by_regime(
            entries=[True, False],
            regimes=[MarketRegime.BULL],
            excluded_regimes={MarketRegime.BEAR},
        )
