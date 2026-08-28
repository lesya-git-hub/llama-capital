from models.pipeline_status import PipelineStatus
from models.stock import Stock
from workflows.research_orchestrator import (
    ResearchOrchestrator,
)
from models.evidence import Evidence
from models.enums import Recommendation
from models.event_analysis import (
    ArticleKind,
    EventAnalysis,
    EventType,
    ImpactDirection,
)
from models.event_cluster import EventCluster
from models.research_report import ResearchReport

def test_orchestrator_returns_no_action_when_no_events() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    orchestrator = ResearchOrchestrator()

    result = orchestrator.run(
        stock=stock,
        ranked_opportunities=[],
    )

    assert result.status == PipelineStatus.NO_ACTION
    assert result.stock.ticker == "RKLB"
    assert result.research_report is None

class FakeOpportunityPipeline:
    def __init__(self) -> None:
        self.received_opportunity = None

    def run(self, opportunity):
        self.received_opportunity = opportunity

        report = ResearchReport(
            stock=opportunity.stock,
            summary="Test research completed.",
            strengths=["Test strength."],
            risks=["Test risk."],
            recommendation=Recommendation.RESEARCH,
            confidence=80.0,
        )

        return (
            report,
            True,
            [],
            True,
            [],
        )

def test_orchestrator_returns_research_completed() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    evidence = Evidence(
        stock=stock,
        source="Reuters",
        headline="Rocket Lab wins major government contract",
        content="Rocket Lab was awarded a major contract.",
        url="https://example.com",
    )

    cluster = EventCluster(
        stock=stock,
        title=evidence.headline,
        evidence_items=[evidence],
    )

    analysis = EventAnalysis(
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
    )

    fake_pipeline = FakeOpportunityPipeline()

    orchestrator = ResearchOrchestrator(
        opportunity_pipeline=fake_pipeline,
    )

    result = orchestrator.run(
        stock=stock,
        ranked_opportunities=[analysis],
    )

    assert (
        result.status
        == PipelineStatus.RESEARCH_COMPLETED
    )
    assert result.stock.ticker == "RKLB"
    assert (
        result.selected_event
        == "Rocket Lab wins major government contract"
    )
    assert result.research_report is not None
    assert result.qa_passed is True
    assert result.iqa_passed is True

    assert fake_pipeline.received_opportunity is not None
    assert (
        fake_pipeline.received_opportunity.event
        == analysis.cluster.title
    )
    assert (
        fake_pipeline.received_opportunity.opportunity_score
        == 80.0
    )