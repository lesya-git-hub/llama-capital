from models.shortlist_intelligence_result import (
    ShortlistIntelligenceResult,
)
from models.shortlist_research_result import (
    ResearchFailure,
    ShortlistResearchResult,
)
from workflows.research_orchestrator import (
    ResearchOrchestrator,
)


class ShortlistResearchPipeline:
    def __init__(
        self,
        research_orchestrator: ResearchOrchestrator | None = None,
    ) -> None:
        self.research_orchestrator = (
            research_orchestrator
            or ResearchOrchestrator()
        )

    def run(
        self,
        intelligence_result: ShortlistIntelligenceResult,
    ) -> ShortlistResearchResult:
        results_by_ticker = {}
        failures = []

        for (
            ticker,
            analyses,
        ) in intelligence_result.analyses_by_ticker.items():
            if not analyses:
                continue

            stock = analyses[0].cluster.stock

            try:
                result = self.research_orchestrator.run(
                    stock=stock,
                    ranked_opportunities=analyses,
                )

                results_by_ticker[ticker] = result

            except Exception as error:
                failures.append(
                    ResearchFailure(
                        ticker=ticker,
                        reason=str(error),
                    )
                )

        return ShortlistResearchResult(
            results_by_ticker=results_by_ticker,
            failures=failures,
        )