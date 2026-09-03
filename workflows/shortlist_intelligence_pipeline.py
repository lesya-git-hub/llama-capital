from models.screening_result import ScreeningResult
from models.shortlist_intelligence_result import (
    IntelligenceFailure,
    ShortlistIntelligenceResult,
)
from workflows.intelligence_pipeline import (
    IntelligencePipeline,
)


class ShortlistIntelligencePipeline:
    def __init__(
        self,
        intelligence_pipeline: IntelligencePipeline,
    ) -> None:
        self.intelligence_pipeline = (
            intelligence_pipeline
        )

    def run(
        self,
        candidates: list[ScreeningResult],
        *,
        max_evidence: int = 10,
    ) -> ShortlistIntelligenceResult:
        analyses_by_ticker = {}
        failures = []

        for candidate in candidates:
            stock = candidate.stock

            try:
                analyses = (
                    self.intelligence_pipeline.run(
                        stock,
                        max_evidence=max_evidence,
                    )
                )

                analyses_by_ticker[
                    stock.ticker
                ] = analyses

            except Exception as error:
                failures.append(
                    IntelligenceFailure(
                        ticker=stock.ticker,
                        reason=str(error),
                    )
                )

        return ShortlistIntelligenceResult(
            analyses_by_ticker=analyses_by_ticker,
            failures=failures,
        )