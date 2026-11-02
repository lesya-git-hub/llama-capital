
"""Compare baseline and regime-filtered backtests across stocks."""
from tools.backtest_comparison import compare_backtests
from tools.historical_data import (
    download_historical_data,
    extract_ohlcv_arrays,
)
from tools.historical_signals import (
    generate_historical_signals,
    generate_mean_reversion_exits,
)
from tools.historical_simulator import simulate_long_only
from tools.market_regimes import (
    MarketRegime,
    filter_entries_by_regime,
    generate_historical_regimes,
)


TICKERS = ("MSFT", "AAPL", "JPM", "XOM", "JNJ", "WMT")
START = "2020-01-01"
END = "2025-01-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-11-01"

def main():
    print("MULTI-STOCK BACKTEST")
    print(f"Period: {START} to {END} (end exclusive)")

    comparisons = []

    for ticker in TICKERS:
        data = download_historical_data(
            ticker=ticker,
            start=START,
            end=END,
        )

        prices = extract_ohlcv_arrays(data)

        entries, atr_values = generate_historical_signals(
            ticker=ticker,
            highs=prices["highs"],
            lows=prices["lows"],
            closes=prices["closes"],
            volumes=prices["volumes"],
            strategy="mean_reversion",
        )

        exits = generate_mean_reversion_exits(
            prices["closes"]
        )

        regimes = generate_historical_regimes(
            highs=prices["highs"],
            lows=prices["lows"],
            closes=prices["closes"],
        )

        filtered_entries = filter_entries_by_regime(
            entries=entries,
            regimes=regimes,
            excluded_regimes={MarketRegime.BEAR},
        )

        common = dict(
            opens=prices["opens"],
            exit_signals=exits,
            atr_values=atr_values,
            lows=prices["lows"],
            closes=prices["closes"],
            initial_cash=10_000,
        )

        baseline = simulate_long_only(
            entry_signals=entries,
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
        comparisons.append(comparison)

        print(
            f"{ticker:5} | "
            f"Baseline: {baseline.total_return_pct:+7.2f}% "
            f"({len(baseline.trades)} trades) | "
            f"Filtered: {filtered.total_return_pct:+7.2f}% "
            f"({len(filtered.trades)} trades) | "
            f"DD: {baseline.max_drawdown_pct:.2f}% "
            f"-> {filtered.max_drawdown_pct:.2f}%"
        )
        print(
            f"      Return improvement: "
            f"{comparison.return_improvement_pp:+.2f} pp | "
            f"Drawdown reduction: "
            f"{comparison.drawdown_reduction_pp:+.2f} pp"
        )
    
    count = len(comparisons)

    improved_returns = sum(
        c.return_improvement_pp > 0
        for c in comparisons
    )

    reduced_drawdowns = sum(
        c.drawdown_reduction_pp > 0
        for c in comparisons
    )

    average_return_improvement = sum(
        c.return_improvement_pp
        for c in comparisons
    ) / count

    average_drawdown_reduction = sum(
        c.drawdown_reduction_pp
        for c in comparisons
    ) / count

    baseline_trades = sum(
        c.baseline_trades for c in comparisons
    )

    filtered_trades = sum(
        c.filtered_trades for c in comparisons
    )

    print("\nAGGREGATE SUMMARY")
    print(f"Stocks tested: {count}")
    print(f"Returns improved: {improved_returns}/{count}")
    print(f"Drawdowns reduced: {reduced_drawdowns}/{count}")
    print(
        f"Average return improvement: "
        f"{average_return_improvement:+.2f} pp"
    )
    print(
        f"Average drawdown reduction: "
        f"{average_drawdown_reduction:+.2f} pp"
    )
    print(
        f"Total trades: {baseline_trades} baseline "
        f"-> {filtered_trades} filtered"
    )

if __name__ == "__main__":
    main()
