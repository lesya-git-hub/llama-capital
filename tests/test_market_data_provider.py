from models.stock import Stock
from providers.mock_market_data_provider import (
    MockMarketDataProvider,
)


def test_mock_market_data_provider_returns_snapshot() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    provider = MockMarketDataProvider()

    snapshot = provider.fetch(stock)

    assert snapshot.stock.ticker == "RKLB"
    assert snapshot.market_cap_billion == 8.5
    assert snapshot.above_200_ema is True
    assert snapshot.source == "mock"