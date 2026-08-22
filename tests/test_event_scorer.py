from models.evidence import Evidence
from models.event_analysis import EventType, ImpactDirection
from models.event_analyst_output import EventAnalystOutput
from models.event_cluster import EventCluster
from models.stock import Stock

from tools.event_scorer import (
    analyze_event,
    calculate_corroboration,
    calculate_source_quality,
)
from models.event_analysis import (
    ArticleKind,
    EventType,
    ImpactDirection,
)

def make_cluster(
    headline: str,
    sources: list[str],
) -> EventCluster:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    evidence_items = [
        Evidence(
            stock=stock,
            source=source,
            headline=headline,
            content="",
            url=f"https://example.com/{index}",
        )
        for index, source in enumerate(sources)
    ]

    return EventCluster(
        stock=stock,
        title=headline,
        evidence_items=evidence_items,
    )


class FakeEventAnalyst:
    def analyze(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        if "high materiality" in cluster.title.lower():
            materiality = 9.0
            impact = -8.0
            direction = ImpactDirection.STRONGLY_NEGATIVE
        else:
            materiality = 2.0
            impact = 5.0
            direction = ImpactDirection.POSITIVE

        return EventAnalystOutput(
            event_type=EventType.CONTRACT,
            impact_direction=direction,
            impact_score=impact,
            materiality_score=materiality,
            summary=cluster.title,
            bull_case=["Test bull case."],
            bear_case=["Test bear case."],
            uncertainties=["Test uncertainty."],
            rationale="Test analysis.",
            article_kind=ArticleKind.CORPORATE_EVENT,
            is_primary_event=True,
        )


def test_high_materiality_event_scores_higher(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tools.event_scorer.EventAnalyst",
        FakeEventAnalyst,
    )

    high = make_cluster(
        "High materiality Rocket Lab contract",
        ["Reuters"],
    )

    low = make_cluster(
        "Low materiality Rocket Lab contract",
        ["Reuters"],
    )

    high_result = analyze_event(high)
    low_result = analyze_event(low)

    assert high_result.opportunity_score > low_result.opportunity_score


def test_negative_event_can_still_have_high_opportunity_score(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tools.event_scorer.EventAnalyst",
        FakeEventAnalyst,
    )

    cluster = make_cluster(
        "High materiality Rocket Lab contract",
        ["Reuters"],
    )

    result = analyze_event(cluster)

    assert result.impact_score < 0
    assert result.opportunity_score >= 50


def test_source_quality_is_bounded() -> None:
    cluster = make_cluster(
        "Rocket Lab contract",
        ["Reuters", "Unknown Source"],
    )

    score = calculate_source_quality(cluster)

    assert 0 <= score <= 10


def test_corroboration_rewards_independent_sources() -> None:
    one_source = make_cluster(
        "Rocket Lab contract",
        ["Reuters"],
    )

    three_sources = make_cluster(
        "Rocket Lab contract",
        [
            "Reuters",
            "Bloomberg",
            "Yahoo",
        ],
    )

    assert (
        calculate_corroboration(three_sources)
        > calculate_corroboration(one_source)
    )


def test_opportunity_score_stays_within_bounds(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tools.event_scorer.EventAnalyst",
        FakeEventAnalyst,
    )

    cluster = make_cluster(
        "High materiality Rocket Lab contract",
        [
            "Reuters",
            "Bloomberg",
            "Yahoo",
        ],
    )

    result = analyze_event(cluster)

    assert 0 <= result.opportunity_score <= 100