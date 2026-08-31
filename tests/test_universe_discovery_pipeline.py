from models.market_snapshot import MarketSnapshot
from models.stock import Stock
from providers.mock_universe_provider import (
    MockUniverseProvider,
)
from workflows.universe_discovery_pipeline import (
    UniverseDiscoveryPipeline,
)


class FakeMarketDataProvider:
    def fetch(
        self,
        stock: Stock,
    ) -> MarketSnapshot:
        scores = {
            "AAA": (20.0, 30.0, 0.5, True),
            "BBB": (10.0, 20.0, 0.5, False),
            "CCC": (0.5, 5.0, 2.0, True),
        }

        (
            market_cap,
            revenue_growth,
            debt_to_equity,
            above_ema,
        ) = scores[stock.ticker]

        return MarketSnapshot(
            stock=stock,
            market_cap_billion=market_cap,
            revenue_growth_percent=revenue_growth,
            debt_to_equity=debt_to_equity,
            price=100.0,
            ema_200=90.0,
            above_200_ema=above_ema,
            source="test",
        )


def test_universe_discovery_returns_ranked_results() -> None:
    pipeline = UniverseDiscoveryPipeline(
        universe_provider=MockUniverseProvider(),
        market_data_provider=FakeMarketDataProvider(),
    )

    discovery_result = pipeline.run()

    results = discovery_result.screening_results

    assert len(results) == 3

    assert results[0].stock.ticker == "AAA"
    assert results[0].score == 100.0

    assert results[1].stock.ticker == "BBB"
    assert results[1].score == 80.0

    assert results[2].stock.ticker == "CCC"
    assert results[2].score == 20.0

def test_discovery_limits_market_data_calls() -> None:
    class CountingMarketDataProvider(
        FakeMarketDataProvider
    ):
        def __init__(self) -> None:
            self.calls = 0

        def fetch(
            self,
            stock: Stock,
        ) -> MarketSnapshot:
            self.calls += 1

            return super().fetch(stock)

    provider = CountingMarketDataProvider()

    from tools.universe_candidate_filter import (
        UniverseCandidateFilter,
    )

    pipeline = UniverseDiscoveryPipeline(
        universe_provider=MockUniverseProvider(),
        market_data_provider=provider,
        candidate_filter=UniverseCandidateFilter(
            max_candidates=2,
        ),
    )

    discovery_result = pipeline.run()

    results = discovery_result.screening_results

    assert len(results) == 2
    assert provider.calls == 2

def test_discovery_continues_when_one_candidate_fails() -> None:
    class FailingMarketDataProvider(
        FakeMarketDataProvider
    ):
        def fetch(
            self,
            stock: Stock,
        ) -> MarketSnapshot:
            if stock.ticker == "BBB":
                raise ValueError(
                    "Market data unavailable."
                )

            return super().fetch(stock)

    pipeline = UniverseDiscoveryPipeline(
        universe_provider=MockUniverseProvider(),
        market_data_provider=FailingMarketDataProvider(),
    )

    result = pipeline.run()

    assert len(result.screening_results) == 2
    assert len(result.failures) == 1

    assert result.failures[0].ticker == "BBB"
    assert (
        result.failures[0].reason
        == "Market data unavailable."
    )