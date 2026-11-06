from dataclasses import replace
from datetime import date, timedelta

import pytest

from tools.historical_simulator import simulate_long_only
from tools.portfolio_simulator import PortfolioSeries, simulate_portfolio


def stock(opens=(100, 100, 100), closes=None, entries=(True, False, False),
          exits=(False, False, False)):
    return PortfolioSeries(
        dates=tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(len(opens))),
        opens=opens, closes=closes if closes is not None else opens,
        entry_signals=entries, exit_signals=exits,
    )


def run(series, **kwargs):
    return simulate_portfolio(series, initial_cash=1000, fee_rate=0,
                              slippage_rate=0, **kwargs)


def test_simultaneous_positions_share_cash_and_equity_budget():
    result = run({'BBB': stock(), 'AAA': stock()}, max_position_fraction=0.5)
    assert [(p.ticker, p.quantity) for p in result.positions] == [('AAA', 5), ('BBB', 5)]
    assert result.final_cash == 0
    assert result.equity_curve == (1000, 1000, 1000)
    assert result.trades == ()


def test_alphabetical_priority_is_independent_of_insertion_order():
    a = run({'BBB': stock(), 'AAA': stock()}, max_position_fraction=0.8)
    b = run({'AAA': stock(), 'BBB': stock()}, max_position_fraction=0.8)
    assert a == b
    assert [(p.ticker, p.quantity) for p in a.positions] == [('AAA', 8), ('BBB', 2)]
    assert a.final_cash >= 0


def test_opening_exit_funds_alphabetically_earlier_entry():
    result = run({
        'ZZZ': stock(opens=(100, 100, 110), exits=(False, True, False)),
        'AAA': stock(entries=(False, True, False)),
    }, max_position_fraction=1)
    assert [(p.ticker, p.quantity) for p in result.positions] == [('AAA', 11)]
    assert result.trades[0].ticker == 'ZZZ'
    assert result.trades[0].trade.net_pnl == 100
    assert result.final_cash == 0
    assert result.final_equity == 1100


def test_costs_and_closed_trade_pnl_reconcile_with_single_stock():
    data = stock(opens=(100, 110, 120), exits=(False, True, False))
    result = simulate_portfolio({'AAA': data}, initial_cash=1000, max_position_fraction=1)
    single = simulate_long_only(data.opens, data.entry_signals, data.exit_signals,
                               initial_cash=1000, max_position_fraction=1, closes=data.closes)
    assert result.final_cash == pytest.approx(single.final_cash)
    assert result.equity_curve == pytest.approx(single.equity_curve)
    assert result.trades[0].trade == single.trades[0]
    assert result.trades[0].trade.quantity == 9
    assert result.trades[0].trade.entry_day == 1
    assert result.trades[0].trade.exit_day == 2
    assert result.final_cash == pytest.approx(1000 + sum(t.trade.net_pnl for t in result.trades))
    assert result.positions == ()


def test_open_positions_mark_to_close_with_entry_costs_only():
    result = simulate_portfolio({'AAA': stock(closes=(100, 120, 130))},
                                initial_cash=1000, max_position_fraction=1,
                                fee_rate=0.01, slippage_rate=0.02)
    expected_cash = 1000 - 9 * 100 * 1.02 * 1.01
    assert result.final_cash == pytest.approx(expected_cash)
    assert result.equity_curve == pytest.approx((1000, expected_cash + 9 * 120,
                                                expected_cash + 9 * 130))
    assert result.final_equity == pytest.approx(result.final_cash + 9 * 130)
    assert result.positions[0].quantity == 9
    assert result.trades == ()


def test_multiple_stocks_closed_pnl_reconciles():
    result = simulate_portfolio({
        'AAA': stock(opens=(100, 100, 120), exits=(False, True, False)),
        'BBB': stock(opens=(50, 50, 40), exits=(False, True, False)),
    }, initial_cash=1000, max_position_fraction=0.5)
    assert len(result.trades) == 2
    assert result.positions == ()
    assert result.final_equity == pytest.approx(result.final_cash)
    assert result.final_cash == pytest.approx(1000 + sum(t.trade.net_pnl for t in result.trades))


def test_repeated_entries_do_not_top_up_and_exit_prevents_same_day_reentry():
    result = run({'AAA': stock(entries=(True, True, True), exits=(False, True, False))},
                 max_position_fraction=0.5)
    assert len(result.trades) == 1
    assert result.trades[0].trade.quantity == 5
    assert result.positions == ()
    held = run({'AAA': stock(entries=(True, True, True))}, max_position_fraction=0.5)
    assert held.positions[0].quantity == 5


def test_last_signal_and_unheld_exit_have_no_effect():
    result = run({'AAA': stock(entries=(False, False, True), exits=(True, False, False))})
    assert result.final_cash == 1000
    assert result.equity_curve == (1000, 1000, 1000)
    assert result.positions == result.trades == ()


def test_unaffordable_whole_share_is_skipped():
    result = run({'AAA': stock(opens=(2000, 2000, 2000))}, max_position_fraction=1)
    assert result.positions == ()
    assert result.final_cash == 1000


def test_sizing_uses_current_opening_equity_without_future_closes():
    result = run({
        'AAA': stock(opens=(100, 100, 200), closes=(100, 100, 10)),
        'BBB': stock(entries=(False, True, False)),
    }, max_position_fraction=0.4)
    # Four AAA shares plus 600 cash are worth 1400 at the second open.
    # BBB's budget is 560, without using AAA's later closing price of 10.
    assert [(p.ticker, p.quantity) for p in result.positions] == [('AAA', 4), ('BBB', 5)]
    assert result.final_cash == 100
    assert result.equity_curve == (1000, 1000, 640)


@pytest.mark.parametrize('field,value', [
    ('initial_cash', 0), ('initial_cash', float('nan')), ('initial_cash', True),
    ('max_position_fraction', 0), ('max_position_fraction', 1.1),
    ('fee_rate', -0.1), ('fee_rate', float('inf')), ('fee_rate', 1),
    ('slippage_rate', float('nan')), ('slippage_rate', 1),
])
def test_invalid_parameters(field, value):
    with pytest.raises(ValueError):
        simulate_portfolio({'AAA': stock()}, **{field: value})


@pytest.mark.parametrize('changes', [
    {'opens': (100, 0, 100)}, {'closes': (100, float('nan'), 100)},
    {'opens': (100, float('inf'), 100)}, {'closes': (100, -1, 100)},
    {'opens': (100, True, 100)}, {'opens': (100, 100)},
    {'entry_signals': (True, False)}, {'exit_signals': (False, 1, False)},
    {'entry_signals': (True, None, False)},
    {'dates': (date(2020, 1, 1),) * 3},
    {'dates': (date(2020, 1, 3), date(2020, 1, 2), date(2020, 1, 1))},
    {'dates': ('2020-01-01', '2020-01-02', '2020-01-03')},
])
def test_invalid_series(changes):
    with pytest.raises(ValueError):
        run({'AAA': replace(stock(), **changes)})


def test_rejects_misaligned_dates_even_with_equal_lengths():
    shifted = replace(stock(), dates=tuple(d + timedelta(days=1) for d in stock().dates))
    with pytest.raises(ValueError, match='synchronized'):
        run({'AAA': stock(), 'BBB': shifted})


@pytest.mark.parametrize('series', [{}, {'': stock()}, {' ': stock()}, {1: stock()}])
def test_invalid_universe(series):
    with pytest.raises(ValueError):
        run(series)


def test_rejects_short_history():
    with pytest.raises(ValueError, match='two sessions'):
        run({'AAA': stock(opens=(100,), entries=(False,), exits=(False,))})


@pytest.mark.parametrize('opens,lows,exits,reason', [
    ((100, 100, 90), (99, 99, 89), (False, False, False), 'stop_gap'),
    ((100, 100, 100), (99, 99, 96), (False, False, False), 'stop_intraday'),
    ((100, 100, 100), (99, 96, 99), (False, False, False), 'stop_intraday'),
    ((100, 100, 90), (99, 99, 89), (False, True, False), 'stop_gap'),
    ((100, 100, 100), (99, 99, 96), (False, True, False), 'signal'),
])
def test_atr_execution_matches_single_stock_with_costs(opens, lows, exits, reason):
    data = replace(stock(opens=opens, exits=exits), atr_values=(2, 50, 50), lows=lows)
    result = simulate_portfolio({'AAA': data}, initial_cash=1000, max_position_fraction=1)
    single = simulate_long_only(
        data.opens, data.entry_signals, data.exit_signals, initial_cash=1000,
        max_position_fraction=1, atr_values=data.atr_values, lows=data.lows,
        closes=data.closes,
    )
    assert len(result.trades) == 1
    assert result.trades[0].trade == single.trades[0]
    assert result.trades[0].trade.exit_reason == reason
    assert result.equity_curve == pytest.approx(single.equity_curve)
    assert result.final_cash == pytest.approx(1000 + result.trades[0].trade.net_pnl)
    assert result.positions == ()


def test_same_day_stop_has_both_execution_costs_and_matching_days():
    data = replace(stock(), atr_values=(2, 2, 2), lows=(99, 96, 99))
    result = simulate_portfolio({'AAA': data}, initial_cash=1000, max_position_fraction=1)
    trade = result.trades[0].trade
    # Risk budget 10 / distance 3 = 3 shares; slipped entry 100.1, stop 97.1.
    entry_cost = 3 * 100 * 1.001 * 1.001
    proceeds = 3 * 97.1 * 0.999 * 0.999
    assert trade.quantity == 3
    assert trade.entry_day == trade.exit_day == 1
    assert trade.exit_price == pytest.approx(97.1)
    assert trade.net_pnl == pytest.approx(proceeds - entry_cost)
    assert result.final_cash == pytest.approx(1000 - entry_cost + proceeds)


def test_atr_sizing_respects_risk_position_and_cash_caps():
    low_atr = replace(stock(), atr_values=(1, 1, 1))
    high_atr = replace(stock(), atr_values=(4, 4, 4))
    low = run({'AAA': low_atr})
    high = run({'AAA': high_atr})
    assert low.positions[0].quantity == 2  # 20% position cap
    assert high.positions[0].quantity == 1  # 10 / 6 risk cap
    shared = run({'BBB': low_atr, 'AAA': low_atr}, max_position_fraction=0.8,
                 risk_fraction=1)
    assert [(p.ticker, p.quantity) for p in shared.positions] == [('AAA', 8), ('BBB', 2)]
    assert shared.final_cash == 0


def test_atr_uses_previous_value_and_stop_remains_fixed():
    data = replace(stock(), atr_values=(2, 50, 0.01), lows=(99, 99, 98))
    result = run({'AAA': data}, max_position_fraction=1)
    assert result.positions[0].quantity == 3
    assert result.positions[0].stop_price == 97
    assert result.trades == ()


def test_gap_stop_releases_cash_before_entries_and_prevents_reentry():
    data = replace(stock(opens=(100, 100, 90), entries=(True, True, False)),
                   atr_values=(2, 2, 2))
    result = run({'ZZZ': data, 'AAA': stock(entries=(False, True, False))},
                 max_position_fraction=1, risk_fraction=1)
    assert [(p.ticker, p.quantity) for p in result.positions] == [('AAA', 9)]
    assert result.trades[0].ticker == 'ZZZ'
    assert result.trades[0].trade.exit_reason == 'stop_gap'
    assert result.final_cash == 0


def test_intraday_stop_proceeds_cannot_fund_opening_entries():
    data = replace(stock(), atr_values=(2, 2, 2), lows=(99, 96, 99))
    result = run({'AAA': data, 'BBB': stock()}, max_position_fraction=1, risk_fraction=1)
    assert result.positions == ()  # BBB could not buy at the open
    assert len(result.trades) == 1
    assert result.trades[0].ticker == 'AAA'
    assert result.final_cash == 970


def test_mixed_atr_and_non_atr_positions_reconcile():
    stopped = replace(stock(), atr_values=(2, 2, 2), lows=(99, 96, 99))
    result = run({'AAA': stopped, 'BBB': stock(closes=(100, 110, 120))})
    assert result.positions[0].ticker == 'BBB'
    assert result.positions[0].stop_price is None
    # AAA cost 200, stop proceeds 194; BBB cost 200 and ends worth 240.
    assert result.final_cash == 794
    assert result.final_equity == 1034
    assert result.final_equity == result.final_cash + result.positions[0].quantity * 120


def test_atr_warmup_and_last_day_missing_atr_are_allowed():
    data = replace(stock(entries=(False, True, True)), atr_values=(None, 2, None))
    result = run({'AAA': data})
    assert result.positions[0].entry_day == 2


def test_low_prices_without_atr_preserve_previous_behavior():
    data = stock()
    assert run({'AAA': data}) == run({'AAA': replace(data, lows=(1, 1, 1))})


@pytest.mark.parametrize('changes', [
    {'atr_values': (2, 2)}, {'atr_values': (None, 2, 2)},
    {'atr_values': (0, 2, 2)}, {'atr_values': (-1, 2, 2)},
    {'atr_values': (float('nan'), 2, 2)}, {'atr_values': (float('inf'), 2, 2)},
    {'atr_values': (True, 2, 2)}, {'lows': (99, 99)},
    {'lows': (99, 0, 99)}, {'lows': (99, float('nan'), 99)},
    {'lows': (99, 101, 99)}, {'closes': (100, 98, 100), 'lows': (99, 99, 99)},
])
def test_invalid_atr_and_lows(changes):
    with pytest.raises(ValueError):
        run({'AAA': replace(stock(), **changes)})


@pytest.mark.parametrize('kwargs', [
    {'risk_fraction': 0}, {'risk_fraction': 1.1}, {'risk_fraction': float('nan')},
    {'atr_multiplier': 0}, {'atr_multiplier': -1}, {'atr_multiplier': float('inf')},
])
def test_invalid_risk_parameters(kwargs):
    with pytest.raises(ValueError):
        run({'AAA': stock()}, **kwargs)


def test_rejects_nonpositive_atr_stop():
    with pytest.raises(ValueError, match='stop must remain above zero'):
        run({'AAA': replace(stock(), atr_values=(100, 100, 100))})


def test_portfolio_metrics_from_known_equity_path():
    result = run({'AAA': stock(closes=(100, 110, 99))}, max_position_fraction=1)
    assert result.equity_curve == (1000, 1100, 990)
    assert result.total_return_pct == pytest.approx(-1)
    assert result.annualized_return_pct == pytest.approx((0.99 ** 126 - 1) * 100)
    assert result.annualized_volatility_pct == pytest.approx((0.02 * 252) ** 0.5 * 100)
    assert result.sharpe_ratio == pytest.approx(0, abs=1e-12)
    assert result.max_drawdown_pct == pytest.approx(10)
    assert result.completed_trade_count == 0
    assert result.trade_expectancy is None
    assert result.trade_expectancy_pct is None


def test_combined_portfolio_offsets_stock_risk():
    result = run({
        'AAA': stock(closes=(100, 120, 80)),
        'BBB': stock(closes=(100, 80, 120)),
    }, max_position_fraction=0.5)
    assert result.equity_curve == (1000, 1000, 1000)
    assert result.total_return_pct == 0
    assert result.annualized_return_pct == 0
    assert result.annualized_volatility_pct == 0
    assert result.max_drawdown_pct == 0
    assert result.sharpe_ratio is None


def test_pooled_completed_trade_expectancy_is_not_portfolio_return():
    result = run({
        'AAA': stock(opens=(100, 100, 120), exits=(False, True, False)),
        'BBB': stock(opens=(50, 50, 45), exits=(False, True, False)),
    }, max_position_fraction=0.4)
    assert [t.trade.net_pnl for t in result.trades] == [80, -40]
    assert result.completed_trade_count == 2
    assert result.trade_expectancy == 20
    assert result.trade_expectancy_pct == pytest.approx(5)
    assert result.total_return_pct == pytest.approx(4)


def test_trade_expectancy_includes_costs_and_excludes_open_positions():
    result = simulate_portfolio({
        'AAA': stock(opens=(100, 100, 110), exits=(False, True, False)),
        'BBB': stock(),
    }, initial_cash=1000, max_position_fraction=0.5)
    # AAA buys four shares; net round-trip P&L includes entry and exit costs.
    expected_pnl = 4 * (110 * 0.999 * 0.999 - 100 * 1.001 * 1.001)
    assert len(result.positions) == 1
    assert result.completed_trade_count == 1
    assert result.trade_expectancy == pytest.approx(expected_pnl)
    assert result.trade_expectancy_pct == pytest.approx(
        expected_pnl / (4 * 100 * 1.001 * 1.001) * 100
    )


@pytest.mark.parametrize('sessions', [2, 3])
def test_no_trade_flat_portfolio_metrics(sessions):
    result = run({'AAA': stock(opens=(100,) * sessions,
                               entries=(False,) * sessions, exits=(False,) * sessions)})
    assert result.total_return_pct == result.annualized_return_pct == 0
    assert result.annualized_volatility_pct == result.max_drawdown_pct == 0
    assert result.sharpe_ratio is None
    assert result.completed_trade_count == 0
    assert result.trade_expectancy is result.trade_expectancy_pct is None


def test_two_session_nonflat_metrics_have_short_series_conventions():
    result = run({'AAA': stock(opens=(100, 100), closes=(100, 110),
                               entries=(True, False), exits=(False, False))},
                 max_position_fraction=1)
    assert result.total_return_pct == pytest.approx(10)
    assert result.annualized_return_pct == pytest.approx((1.1 ** 252 - 1) * 100)
    assert result.annualized_volatility_pct == 0
    assert result.sharpe_ratio is None


def test_metrics_match_single_stock_reporting():
    data = replace(stock(opens=(100, 100, 90)), atr_values=(2, 2, 2), lows=(99, 99, 89))
    portfolio = simulate_portfolio({'AAA': data}, initial_cash=1000)
    single = simulate_long_only(data.opens, data.entry_signals, data.exit_signals,
                               initial_cash=1000, atr_values=data.atr_values,
                               lows=data.lows, closes=data.closes)
    for metric in ('total_return_pct', 'annualized_return_pct', 'annualized_volatility_pct',
                   'sharpe_ratio', 'max_drawdown_pct', 'trade_expectancy', 'trade_expectancy_pct'):
        assert getattr(portfolio, metric) == getattr(single, metric)


def test_legacy_result_construction_remains_supported():
    from tools.portfolio_simulator import PortfolioSimulationResult

    result = PortfolioSimulationResult((date(2020, 1, 1),), 1000, (), (), (1000,), 1000)
    assert result.final_equity == 1000
    assert result.completed_trade_count == 0
    assert result.trade_expectancy is None
