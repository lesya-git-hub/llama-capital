from providers.finnhub_universe_provider import (
    FinnhubUniverseProvider,
)


def main() -> None:
    provider = FinnhubUniverseProvider()

    stocks = provider.fetch()

    print(
        "Filtered common stocks:",
        len(stocks),
    )

    for stock in stocks[:30]:
        print(
            stock.ticker,
            "|",
            stock.company,
            "|",
            stock.exchange,
        )


if __name__ == "__main__":
    main()