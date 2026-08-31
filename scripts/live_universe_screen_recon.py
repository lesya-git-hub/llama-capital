from config.universe_v01 import UNIVERSE_V01
from providers.configured_universe_provider import (
    ConfiguredUniverseProvider,
)
from providers.finnhub_market_data_provider import (
    FinnhubMarketDataProvider,
)
from providers.finnhub_universe_provider import (
    FinnhubUniverseProvider,
)
from tools.universe_candidate_filter import (
    UniverseCandidateFilter,
)
from workflows.universe_discovery_pipeline import (
    UniverseDiscoveryPipeline,
)


def main() -> None:
    source_provider = FinnhubUniverseProvider()

    universe_provider = ConfiguredUniverseProvider(
        source_provider=source_provider,
        config=UNIVERSE_V01,
    )

    market_data_provider = FinnhubMarketDataProvider()

    pipeline = UniverseDiscoveryPipeline(
        universe_provider=universe_provider,
        market_data_provider=market_data_provider,
        candidate_filter=UniverseCandidateFilter(
            max_candidates=30,
        ),
    )

    discovery = pipeline.run()

    print()
    print("=" * 100)
    print("LIVE UNIVERSE SCREEN")
    print("=" * 100)

    for rank, result in enumerate(
        discovery.screening_results,
        start=1,
    ):
        print()
        print(f"#{rank}")
        print("Ticker:", result.stock.ticker)
        print("Company:", result.stock.company)
        print("Passed:", result.passed)
        print("Score:", result.score)

        for reason in result.reasons:
            print("-", reason)

    print()
    print("=" * 100)
    print("FAILURES")
    print("=" * 100)

    if not discovery.failures:
        print("None")
    else:
        for failure in discovery.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )


if __name__ == "__main__":
    main()