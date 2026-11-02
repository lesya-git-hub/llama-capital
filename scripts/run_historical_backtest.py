
"""Run a historical mean-reversion backtest."""

from tools.historical_data import (
    download_historical_data,
    extract_ohlcv_arrays,
)
from tools.historical_signals import (
    generate_historical_signals,
    generate_mean_reversion_exits,
)
from tools.historical_simulator import simulate_long_only


def main():
    ticker = "MSFT"

    data = download_historical_data(
        ticker=ticker,
        start="2020-01-01",
        end="2025-01-01",
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
