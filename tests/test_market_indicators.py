
import pytest

from tools.market_indicators import sma, rsi, atr, donchian_high, previous_average_volume



def test_sma_calculation():
    assert sma([10, 20, 30, 40, 50], period=5) == 30


def test_sma_uses_latest_prices():
    assert sma([100, 10, 20, 30], period=3) == 20


def test_sma_rejects_insufficient_history():
    with pytest.raises(ValueError):
        sma([10, 20], period=3)


def test_rsi_all_gains():
    prices = list(range(100, 116))
    assert rsi(prices) == 100.0


def test_rsi_all_losses():
    prices = list(range(116, 100, -1))
    assert rsi(prices) == 0.0


def test_rsi_flat_market():
    prices = [100.0] * 20
    assert rsi(prices) == 50.0


def test_rsi_wilder_reference():
    # Wilder's standard 14-period RSI example.
    prices = [
        44.34, 44.09, 44.15, 43.61, 44.33,
        44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28,
        46.00, 46.03, 46.41, 46.22, 45.64,
        46.21,
    ]

    assert rsi(prices) == pytest.approx(62.88, abs=0.1)


def test_rsi_rejects_insufficient_history():
    with pytest.raises(ValueError):
        rsi([100.0] * 14)

def test_atr_constant_range():
    highs = [102.0] * 16
    lows = [98.0] * 16
    closes = [100.0] * 16

    assert atr(highs, lows, closes) == pytest.approx(4.0)


def test_atr_includes_overnight_gap():
    # First 14 true ranges are 2.
    # Final candle gaps upward: TR = 10.
    highs = [101.0] * 15 + [110.0]
    lows = [99.0] * 15 + [108.0]
    closes = [100.0] * 15 + [109.0]

    expected = (13 * 2.0 + 10.0) / 14

    assert atr(highs, lows, closes) == pytest.approx(expected)


def test_atr_rejects_insufficient_history():
    with pytest.raises(ValueError):
        atr(
            [102.0] * 14,
            [98.0] * 14,
            [100.0] * 14,
        )


def test_atr_rejects_invalid_candle():
    highs = [102.0] * 16
    lows = [98.0] * 16
    closes = [100.0] * 16

    highs[5] = 97.0

    with pytest.raises(ValueError):
        atr(highs, lows, closes)


def test_atr_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        atr(
            [102.0] * 16,
            [98.0] * 15,
            [100.0] * 16,
        )

def test_donchian_high_uses_previous_sessions():
    highs = [100.0] * 19 + [110.0, 105.0]

    assert donchian_high(highs) == 110.0


def test_donchian_high_excludes_current_candle():
    # Current candle has the highest price: 150.
    # Historical resistance must remain 100.
    highs = [100.0] * 20 + [150.0]

    assert donchian_high(highs) == 100.0


def test_donchian_high_uses_latest_window():
    # Older resistance of 200 must be ignored.
    highs = [200.0] + [100.0] * 20 + [105.0]

    assert donchian_high(highs) == 100.0


def test_donchian_high_rejects_insufficient_history():
    with pytest.raises(ValueError):
        donchian_high([100.0] * 20)


def test_donchian_high_rejects_invalid_historical_price():
    highs = [100.0] * 20 + [105.0]
    highs[5] = -10.0

    with pytest.raises(ValueError):
        donchian_high(highs)

def test_previous_average_volume_calculation():
    volumes = [1000.0] * 20 + [2000.0]

    assert previous_average_volume(volumes) == 1000.0


def test_previous_average_volume_excludes_current_session():
    # Today's extreme volume must not affect
    # the historical average.
    volumes = [1000.0] * 20 + [1_000_000.0]

    assert previous_average_volume(volumes) == 1000.0


def test_previous_average_volume_uses_latest_window():
    # Old volume spike must be ignored.
    volumes = [100_000.0] + [1000.0] * 20 + [2000.0]

    assert previous_average_volume(volumes) == 1000.0


def test_previous_average_volume_rejects_short_history():
    with pytest.raises(ValueError):
        previous_average_volume([1000.0] * 20)


def test_previous_average_volume_rejects_negative_volume():
    volumes = [1000.0] * 20 + [2000.0]
    volumes[5] = -100.0

    with pytest.raises(ValueError):
        previous_average_volume(volumes)
