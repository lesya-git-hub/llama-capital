from config.universe_v01 import UNIVERSE_V01
from providers.configured_universe_provider import (
    ConfiguredUniverseProvider,
)
from providers.finnhub_universe_provider import (
    FinnhubUniverseProvider,
)


def main() -> None:
    source_provider = FinnhubUniverseProvider()

    provider = ConfiguredUniverseProvider(
        source_provider=source_provider,
        config=UNIVERSE_V01,
    )

    stocks = provider.fetch()

    print(
        "Configured live universe:",
        len(stocks),
    )

    for stock in stocks:
        print(
            stock.ticker,
            "|",
            stock.company,
            "|",
            stock.exchange,
        )


if __name__ == "__main__":
    main()