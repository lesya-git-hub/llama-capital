from models.pipeline_run_result import PipelineRunResult
from models.pipeline_status import PipelineStatus
from models.shortlist_intelligence_result import (
    ShortlistIntelligenceResult,
)
from models.stock import Stock
from workflows.shortlist_research_pipeline import (
    ShortlistResearchPipeline,
)
from models.evidence import Evidence
from models.event_analysis import (
    ArticleKind,
    EventAnalysis,
    EventType,
    ImpactDirection,
)
from models.event_cluster import EventCluster

def make_analysis(
    stock: Stock,
) -> EventAnalysis:
    evidence = Evidence(
        stock=stock,
        source="Reuters",
        headline=f"{stock.company} reports corporate event",
        content="Test evidence.",
        url="https://example.com",
    )

    cluster = EventCluster(
        stock=stock,
        title=evidence.headline,
        evidence_items=[evidence],
    )

    return EventAnalysis(
        cluster=cluster,
        event_type=EventType.CONTRACT,
        article_kind=ArticleKind.CORPORATE_EVENT,
        is_primary_event=True,
        importance_score=8.0,
        source_quality_score=10.0,
        corroboration_score=3.0,
        strategic_relevance_score=8.0,
        impact_direction=ImpactDirection.POSITIVE,
        impact_score=5.0,
        opportunity_score=80.0,
        rationale=["Test rationale."],
        eligible_for_research=True,
        eligibility_reason="eligible for research",
    )

class FakeResearchOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    def run(
        self,
        stock: Stock,
        ranked_opportunities,
    ) -> PipelineRunResult:
        self.calls.append(stock.ticker)

        status = (
            PipelineStatus.RESEARCH_COMPLETED
            if stock.ticker == "CRWD"
            else PipelineStatus.NO_ACTION
        )

        return PipelineRunResult(
            status=status,
            stock=stock,
            reason="Test result.",
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


def test_shortlist_research_processes_each_ticker() -> None:
    amd = make_stock("AMD")
    crwd = make_stock("CRWD")

    intelligence_result = ShortlistIntelligenceResult(
        analyses_by_ticker={
            "AMD": [
                make_analysis(amd)
            ],
            "CRWD": [
                make_analysis(crwd)
            ],
        }
    )

    orchestrator = FakeResearchOrchestrator()

    pipeline = ShortlistResearchPipeline(
        research_orchestrator=orchestrator,
    )

    result = pipeline.run(
        intelligence_result
    )

    assert orchestrator.calls == [
        "AMD",
        "CRWD",
    ]

    assert (
        result.results_by_ticker["AMD"].status
        == PipelineStatus.NO_ACTION
    )

    assert (
        result.results_by_ticker["CRWD"].status
        == PipelineStatus.RESEARCH_COMPLETED
    )

    assert result.failures == []

def test_shortlist_research_continues_after_failure() -> None:
    class FailingResearchOrchestrator(
        FakeResearchOrchestrator
    ):
        def run(
            self,
            stock: Stock,
            ranked_opportunities,
        ) -> PipelineRunResult:
            if stock.ticker == "AMD":
                raise RuntimeError(
                    "Research failed."
                )

            return super().run(
                stock,
                ranked_opportunities,
            )

    amd = make_stock("AMD")
    crwd = make_stock("CRWD")

    intelligence_result = ShortlistIntelligenceResult(
        analyses_by_ticker={
            "AMD": [
                make_analysis(amd)
            ],
            "CRWD": [
                make_analysis(crwd)
            ],
        }
    )

    pipeline = ShortlistResearchPipeline(
        research_orchestrator=(
            FailingResearchOrchestrator()
        ),
    )

    result = pipeline.run(
        intelligence_result
    )

    assert "AMD" not in result.results_by_ticker
    assert "CRWD" in result.results_by_ticker

    assert len(result.failures) == 1
    assert result.failures[0].ticker == "AMD"
    assert (
        result.failures[0].reason
        == "Research failed."
    )