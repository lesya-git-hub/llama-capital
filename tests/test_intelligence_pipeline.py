from models.evidence import Evidence
from models.event_analysis import (
    EventAnalysis,
    EventType,
    ImpactDirection,
)
from models.event_analysis import (
    ArticleKind,
    EventAnalysis,
    EventType,
    ImpactDirection,
)
from models.event_cluster import EventCluster
from models.stock import Stock
from workflows.intelligence_pipeline import IntelligencePipeline


class FakeEvidenceProvider:
    def fetch(self, stock: Stock) -> list[Evidence]:
        return [
            Evidence(
                stock=stock,
                source="Reuters",
                headline="Rocket Lab wins major contract",
                content="",
                url="https://example.com/1",
            ),
            Evidence(
                stock=stock,
                source="Reuters",
                headline="Rocket Lab expands production",
                content="",
                url="https://example.com/2",
            ),
        ]


class FakeClusterer:
    def cluster(
        self,
        evidence_items: list[Evidence],
    ) -> list[EventCluster]:
        return [
            EventCluster(
                stock=evidence_items[0].stock,
                title=evidence_items[0].headline,
                evidence_items=[evidence_items[0]],
            ),
            EventCluster(
                stock=evidence_items[1].stock,
                title=evidence_items[1].headline,
                evidence_items=[evidence_items[1]],
            ),
        ]


def fake_analyze_event(
    cluster: EventCluster,
) -> EventAnalysis:
    score = (
        80.0
        if "contract" in cluster.title.lower()
        else 60.0
    )

    return EventAnalysis(
        cluster=cluster,
        event_type=EventType.CONTRACT,
        importance_score=8.0,
        source_quality_score=10.0,
        corroboration_score=3.0,
        strategic_relevance_score=8.0,
        impact_direction=ImpactDirection.POSITIVE,
        impact_score=5.0,
        opportunity_score=score,
        rationale=["Test analysis."],
        article_kind=ArticleKind.CORPORATE_EVENT,
        is_primary_event=True,
    )


def test_intelligence_pipeline_returns_ranked_analyses(
    monkeypatch,
) -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    pipeline = IntelligencePipeline(
    evidence_provider=FakeEvidenceProvider(),
    clusterer=FakeClusterer(),
    )

    monkeypatch.setattr(
        "workflows.intelligence_pipeline.analyze_event",
        fake_analyze_event,
    )

    results = pipeline.run(
        stock,
        max_evidence=10,
    )

    assert len(results) == 2
    assert results[0].opportunity_score == 80.0
    assert results[1].opportunity_score == 60.0