from models.universe_config import UniverseConfig
from providers.configured_universe_provider import (
    ConfiguredUniverseProvider,
)
from providers.mock_universe_provider import (
    MockUniverseProvider,
)


def test_configured_universe_selects_allowed_tickers() -> None:
    config = UniverseConfig(
        max_candidates=2,
        allowed_tickers={
            "AAA",
            "CCC",
        },
    )

    provider = ConfiguredUniverseProvider(
        source_provider=MockUniverseProvider(),
        config=config,
    )

    stocks = provider.fetch()

    assert [
        stock.ticker
        for stock in stocks
    ] == [
        "AAA",
        "CCC",
    ]


def test_configured_universe_respects_limit() -> None:
    config = UniverseConfig(
        max_candidates=1,
        allowed_tickers={
            "AAA",
            "BBB",
            "CCC",
        },
    )

    provider = ConfiguredUniverseProvider(
        source_provider=MockUniverseProvider(),
        config=config,
    )

    stocks = provider.fetch()

    assert len(stocks) == 1
    assert stocks[0].ticker == "AAA"


def test_configured_universe_empty_config_returns_empty() -> None:
    config = UniverseConfig()

    provider = ConfiguredUniverseProvider(
        source_provider=MockUniverseProvider(),
        config=config,
    )

    assert provider.fetch() == []