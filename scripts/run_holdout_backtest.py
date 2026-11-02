from tools.historical_signals import (
    generate_historical_signals,
    generate_mean_reversion_exits,
)
from tools.market_regimes import (
    MarketRegime,
    generate_historical_regimes,
    filter_entries_by_regime,
)
from tools.historical_simulator import simulate_long_only
from tools.backtest_comparison import compare_backtests
"""Evaluate a fixed strategy on out-of-sample market data."""

from tools.historical_data import (
    download_historical_data,
    extract_ohlcv_arrays,
)


TICKERS = ("MSFT", "AAPL", "JPM", "XOM", "JNJ", "WMT")

WARMUP_START = "2024-01-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-11-01"


def main():
    print("OUT-OF-SAMPLE DATA CHECK")

    for ticker in TICKERS:
        data = download_historical_data(
            ticker=ticker,
            start=WARMUP_START,
            end=HOLDOUT_END,
        )

        prices = extract_ohlcv_arrays(data)

        holdout_mask = data.index >= HOLDOUT_START
        holdout_sessions = int(holdout_mask.sum())
        
        first_holdout_index = next(
            i
            for i, is_holdout in enumerate(holdout_mask)
            if is_holdout
        )
        
        entries, atr_values = generate_historical_signals(
            ticker=ticker,
            highs=prices["highs"],
            lows=prices["lows"],
            closes=prices["closes"],
            volumes=prices["volumes"],
            strategy="mean_reversion",
        )

        simulation_start = first_holdout_index - 1
        
        simulation_opens = prices["opens"][simulation_start:]
        simulation_lows = prices["lows"][simulation_start:]
        simulation_closes = prices["closes"][simulation_start:]
        simulation_entries = entries[simulation_start:]
        simulation_atr = atr_values[simulation_start:]
        
        exits = generate_mean_reversion_exits(
            prices["closes"]
        )

        simulation_exits = exits[simulation_start:]
        
        regimes = generate_historical_regimes(
            highs=prices["highs"],
            lows=prices["lows"],
            closes=prices["closes"],
        )

        simulation_regimes = regimes[simulation_start:]

        filtered_entries = filter_entries_by_regime(
            entries=simulation_entries,
            regimes=simulation_regimes,
            excluded_regimes={MarketRegime.BEAR},
        )
        
        common = dict(
            opens=simulation_opens,
            exit_signals=simulation_exits,
            atr_values=simulation_atr,
            lows=simulation_lows,
            closes=simulation_closes,
            initial_cash=10_000,
        )

        baseline = simulate_long_only(
            entry_signals=simulation_entries,
            **common,
        )

        filtered = simulate_long_only(
            entry_signals=filtered_entries,
            **common,
        )

        comparison = compare_backtests(
            ticker=ticker,
            baseline=baseline,
            filtered=filtered,
        )

        print(
            f"      HOLDOUT {ticker}: "
            f"Baseline {baseline.total_return_pct:+.2f}% "
            f"({len(baseline.trades)} trades) | "
            f"Filtered {filtered.total_return_pct:+.2f}% "
            f"({len(filtered.trades)} trades)"
        )

        print(
            f"      Return improvement: "
            f"{comparison.return_improvement_pp:+.2f} pp | "
            f"Drawdown reduction: "
            f"{comparison.drawdown_reduction_pp:+.2f} pp"
        )

        assert len(simulation_regimes) == len(simulation_opens)
        assert len(filtered_entries) == len(simulation_opens)

        print(
            f"      Entry signals: "
            f"{sum(simulation_entries)} baseline -> "
            f"{sum(filtered_entries)} filtered"
        )


        assert len(simulation_exits) == len(simulation_opens)
        assert len(simulation_entries) == len(simulation_opens)
        assert len(simulation_atr) == len(simulation_opens)

        print(
            f"      Exit signals prepared: "
            f"{len(simulation_exits)} bars"
        )

        print(
            f"      Simulation bars: {len(simulation_opens)} | "
            f"Entry signals: {sum(simulation_entries)}"
        )

        print(
            f"      Signal boundary: "
            f"{data.index[simulation_start].date()} | "
            f"First execution: "
            f"{data.index[first_holdout_index].date()}"
        )

        print(
            f"      Holdout entry signals: "
            f"{sum(entries[first_holdout_index:])}"
        )

        print(
            f"      First holdout index: {first_holdout_index} | "
            f"First holdout date: "
            f"{data.index[first_holdout_index].date()}"
        )


        print(
            f"{ticker}: "
            f"{len(prices['closes'])} total sessions | "
            f"{holdout_sessions} holdout sessions"
        )


if __name__ == "__main__":
    main()
