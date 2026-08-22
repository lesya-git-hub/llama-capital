from agents.event_analyst import EventAnalyst
from models.evidence import Evidence
from models.event_analysis import EventType, ImpactDirection
from models.event_analyst_output import EventAnalystOutput
from models.event_cluster import EventCluster
from models.stock import Stock
from models.event_analysis import (
    ArticleKind,
    EventType,
    ImpactDirection,
)


def make_cluster(
    headline: str = "Rocket Lab wins new Space Force contract",
) -> EventCluster:
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
        headline=headline,
        content="",
        url="https://example.com",
    )

    return EventCluster(
        stock=stock,
        title=headline,
        evidence_items=[evidence],
    )


class SuccessfulProvider:
    def analyze(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        return EventAnalystOutput(
            event_type=EventType.CONTRACT,
            impact_direction=ImpactDirection.POSITIVE,
            impact_score=6.0,
            materiality_score=7.0,
            summary="Rocket Lab won a government contract.",
            bull_case=["Adds government revenue."],
            bear_case=["Contract size may be limited."],
            uncertainties=["Revenue timing is unknown."],
            rationale="Positive contract event.",
            article_kind=ArticleKind.CORPORATE_EVENT,
            is_primary_event=True,
        )


class FailingProvider:
    def analyze(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        raise RuntimeError("Simulated API failure")


def test_event_analyst_uses_llm_result() -> None:
    analyst = EventAnalyst()
    analyst.llm_provider = SuccessfulProvider()

    result = analyst.analyze(make_cluster())

    assert result.event_type == EventType.CONTRACT
    assert result.impact_direction == ImpactDirection.POSITIVE
    assert result.impact_score == 6.0
    assert result.materiality_score == 7.0
    assert result.rationale == "Positive contract event."


def test_event_analyst_uses_fallback_when_llm_fails() -> None:
    analyst = EventAnalyst()
    analyst.llm_provider = FailingProvider()

    result = analyst.analyze(make_cluster())

    assert result.event_type == EventType.CONTRACT
    assert result.impact_direction == ImpactDirection.POSITIVE
    assert result.impact_score == 5.0
    assert result.materiality_score == 5.0
    assert "fallback" in result.rationale.lower()