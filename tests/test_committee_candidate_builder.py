from models.pipeline_run_result import (
    PipelineRunResult,
)
from models.pipeline_status import PipelineStatus
from models.research_report import ResearchReport
from models.screening_result import ScreeningResult
from models.stock import Stock
from tools.committee_candidate_builder import (
    CommitteeCandidateBuilder,
)


def make_stock(
    ticker: str,
) -> Stock:
    return Stock(
        ticker=ticker,
        company=ticker,
        sector="Test",
        industry="Test",
        exchange="NASDAQ",
    )


def make_screening(
    stock: Stock,
) -> ScreeningResult:
    return ScreeningResult(
        stock=stock,
        passed=True,
        score=100.0,
        reasons=[],
    )


def make_report(
    stock: Stock,
) -> ResearchReport:
    return ResearchReport.model_construct(
        stock=stock,
    )


def test_builder_keeps_only_validated_research() -> None:
    amd = make_stock("AMD")
    crwd = make_stock("CRWD")

    screening_results = [
        make_screening(amd),
        make_screening(crwd),
    ]

    class FakeResearchResults:
        results_by_ticker = {
            "AMD": PipelineRunResult(
                status=PipelineStatus.NO_ACTION,
                stock=amd,
            ),
            "CRWD": PipelineRunResult(
                status=PipelineStatus.RESEARCH_COMPLETED,
                stock=crwd,
                research_report=make_report(crwd),
                qa_passed=True,
                iqa_passed=True,
            ),
        }

    builder = CommitteeCandidateBuilder()

    candidates = builder.build(
        screening_results,
        FakeResearchResults(),
    )

    assert len(candidates) == 1
    assert (
        candidates[0].research.stock.ticker
        == "CRWD"
    )