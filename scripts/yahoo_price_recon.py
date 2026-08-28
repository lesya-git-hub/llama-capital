from models.stock import Stock
from providers.yahoo_price_history_provider import (
    YahooPriceHistoryProvider,
)


def main() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    provider = YahooPriceHistoryProvider()

    closes = provider.fetch_daily_closes(
        stock,
        days=365,
    )

    print("Daily closes:", len(closes))

    if closes:
        print("First close:", closes[0])
        print("Last close:", closes[-1])


if __name__ == "__main__":
    main()