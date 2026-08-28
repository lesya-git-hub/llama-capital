from models.stock import Stock
from providers.finnhub_market_data_provider import (
    FinnhubMarketDataProvider,
)


def main() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    provider = FinnhubMarketDataProvider()

    snapshot = provider.fetch(stock)

    print("Ticker:", snapshot.stock.ticker)
    print(
        "Market cap:",
        snapshot.market_cap_billion,
        "B",
    )
    print(
        "Revenue growth:",
        snapshot.revenue_growth_percent,
        "%",
    )
    print(
        "Debt / equity:",
        snapshot.debt_to_equity,
    )
    print(
        "Price:",
        snapshot.price,
    )
    print(
        "EMA 200:",
        snapshot.ema_200,
    )
    print(
        "Above EMA 200:",
        snapshot.above_200_ema,
    )
    print(
        "Source:",
        snapshot.source,
    )


if __name__ == "__main__":
    main()