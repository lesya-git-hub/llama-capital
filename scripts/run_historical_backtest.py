from tools.market_regimes import MarketRegime
"""Run a historical mean-reversion backtest."""
from collections import Counter
from tools.market_regimes import generate_historical_regimes
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
    generate_historical_regimes,
    filter_entries_by_regime,
)

def main():
    ticker = "MSFT"

    data = download_historical_data(
        ticker=ticker,
        start="2020-01-01",
        end="2025-01-01",
    )

    prices = extract_ohlcv_arrays(data)
    
    regimes = generate_historical_regimes(
        highs=prices["highs"],
        lows=prices["lows"],
        closes=prices["closes"],
    )

    regime_counts = Counter(
        regime.value if regime is not None else "warmup"
        for regime in regimes
    )

    print("\nMARKET REGIME DISTRIBUTION")

    for regime, count in sorted(regime_counts.items()):
        percentage = count / len(regimes) * 100
        print(f"{regime}: {count} sessions ({percentage:.1f}%)")


    entries, atr_values = generate_historical_signals(
        ticker=ticker,
        highs=prices["highs"],
        lows=prices["lows"],
        closes=prices["closes"],
        volumes=prices["volumes"],
        strategy="mean_reversion",
    )
    print("\nREGIME AT ENTRY SIGNALS")
    
    filtered_entries = filter_entries_by_regime(
        entries=entries,
        regimes=regimes,
        excluded_regimes={MarketRegime.BEAR},
    )


    print("\nBEAR-MARKET FILTER")
    print(f"Original entry signals: {sum(entries)}")
    print(f"Filtered entry signals: {sum(filtered_entries)}")
    
    for day, entry in enumerate(entries):
        if entry:
            regime = regimes[day]
            label = regime.value if regime is not None else "warmup"
            print(f"{data.index[day].date()}: {label}")
    exits = generate_mean_reversion_exits(
        prices["closes"]
    )
    
    print("\nSIGNAL DATES")

    for day, (entry, exit_signal) in enumerate(
        zip(entries, exits)
    ):
        if entry:
            print(
                f"ENTRY SIGNAL: {data.index[day].date()}"
            )

        if exit_signal and day > 0 and entries[day - 1]:
            print(
                f"EXIT CONDITION: {data.index[day].date()}"
            )

    result = simulate_long_only(
        opens=prices["opens"],
        entry_signals=entries,
        exit_signals=exits,
        atr_values=atr_values,
        lows=prices["lows"],
        closes=prices["closes"],
        initial_cash=10_000,
    )
    
    filtered_result = simulate_long_only(
        opens=prices["opens"],
        entry_signals=filtered_entries,
        exit_signals=exits,
        atr_values=atr_values,
        lows=prices["lows"],
        closes=prices["closes"],
        initial_cash=10_000,
    )

    print("\nBASELINE VS BEAR-MARKET FILTER")
    print(
        f"Baseline: {len(result.trades)} trades | "
        f"Final equity: ${result.final_equity:.2f} | "
        f"Return: {result.total_return_pct:.2f}% | "
        f"Max DD: {result.max_drawdown_pct:.2f}%"
    )
    print(
        f"Filtered: {len(filtered_result.trades)} trades | "
        f"Final equity: ${filtered_result.final_equity:.2f} | "
        f"Return: {filtered_result.total_return_pct:.2f}% | "
        f"Max DD: {filtered_result.max_drawdown_pct:.2f}%"
    )

    print("\nTRADE DETAILS")

    for index, trade in enumerate(result.trades, start=1):
        entry_date = data.index[trade.entry_day].date()
        exit_date = data.index[trade.exit_day].date()

        holding_days = trade.exit_day - trade.entry_day

        print(f"\nTrade {index}")
        print(
            f"Entry: {entry_date} @ ${trade.entry_price:.2f} | "
            f"Exit: {exit_date} @ ${trade.exit_price:.2f} | "
            f"Shares: {trade.quantity} | "
            f"Sessions held: {holding_days} | "
            f"Reason: {trade.exit_reason} | "
            f"Net P&L: ${trade.net_pnl:.2f}"
        )


if __name__ == "__main__":
    main()
