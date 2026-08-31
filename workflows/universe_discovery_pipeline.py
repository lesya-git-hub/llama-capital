from models.universe_discovery_result import (
    UniverseDiscoveryResult,
    UniverseScreeningFailure,
)
from providers.base_market_data_provider import (
    BaseMarketDataProvider,
)
from providers.base_universe_provider import (
    BaseUniverseProvider,
)
from tools.universe_candidate_filter import (
    UniverseCandidateFilter,
)
from workflows.universe_pipeline import UniversePipeline


class UniverseDiscoveryPipeline:
    def __init__(
        self,
        universe_provider: BaseUniverseProvider,
        market_data_provider: BaseMarketDataProvider,
        universe_pipeline: UniversePipeline | None = None,
        candidate_filter: UniverseCandidateFilter | None = None,
    ) -> None:
        self.universe_provider = universe_provider
        self.market_data_provider = market_data_provider
        self.universe_pipeline = (
            universe_pipeline
            or UniversePipeline()
        )
        self.candidate_filter = (
            candidate_filter
            or UniverseCandidateFilter(
                max_candidates=100,
            )
        )

    def run(self) -> UniverseDiscoveryResult:
        stocks = self.universe_provider.fetch()

        candidates = self.candidate_filter.filter(
            stocks
        )

        screening_results = []
        failures = []

        for stock in candidates:
            try:
                snapshot = self.market_data_provider.fetch(
                    stock
                )

                result = self.universe_pipeline.run(
                    snapshot
                )

                screening_results.append(result)

            except Exception as error:
                failures.append(
                    UniverseScreeningFailure(
                        ticker=stock.ticker,
                        reason=str(error),
                    )
                )

        screening_results = sorted(
            screening_results,
            key=lambda result: result.score,
            reverse=True,
        )

        return UniverseDiscoveryResult(
            screening_results=screening_results,
            failures=failures,
        )