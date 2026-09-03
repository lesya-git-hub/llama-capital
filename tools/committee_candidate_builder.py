from models.committee_candidate import (
    CommitteeCandidate,
)
from models.pipeline_status import PipelineStatus
from models.screening_result import ScreeningResult


class CommitteeCandidateBuilder:
    def build(
        self,
        screening_results: list[ScreeningResult],
        research_results,
    ) -> list[CommitteeCandidate]:
        screening_by_ticker = {
            result.stock.ticker: result
            for result in screening_results
        }

        candidates: list[CommitteeCandidate] = []

        for ticker, result in (
            research_results.results_by_ticker.items()
        ):
            if (
                result.status
                != PipelineStatus.RESEARCH_COMPLETED
            ):
                continue

            if result.research_report is None:
                continue

            if result.qa_passed is not True:
                continue

            if result.iqa_passed is not True:
                continue

            screening = screening_by_ticker.get(
                ticker
            )

            if screening is None:
                continue

            candidates.append(
                CommitteeCandidate(
                    screening=screening,
                    research=result.research_report,
                    qa_passed=True,
                    iqa_passed=True,
                )
            )

        return candidates