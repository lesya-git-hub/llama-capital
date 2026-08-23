from models.evidence import Evidence
from models.event_analysis import (
    EventAnalysis,
    EventType,
    ImpactDirection,
)
from models.event_cluster import EventCluster
from models.stock import Stock
from tools.event_eligibility import (
    is_event_eligible,
    select_top_eligible_event,
)
from models.event_analysis import (
    ArticleKind,
    EventAnalysis,
    EventType,
    ImpactDirection,
)

def make_analysis(
    event_type: EventType,
    opportunity_score: float,
    article_kind: ArticleKind = ArticleKind.CORPORATE_EVENT,
    is_primary_event: bool = True,
) -> EventAnalysis:
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
        headline="Rocket Lab event",
        content="",
        url="https://example.com",
    )

    cluster = EventCluster(
        stock=stock,
        title=evidence.headline,
        evidence_items=[evidence],
    )

    return EventAnalysis(
        cluster=cluster,
        event_type=event_type,
        article_kind=article_kind,
        is_primary_event=is_primary_event,
        importance_score=8.0,
        source_quality_score=10.0,
        corroboration_score=3.0,
        strategic_relevance_score=8.0,
        impact_direction=ImpactDirection.POSITIVE,
        impact_score=5.0,
        opportunity_score=opportunity_score,
        rationale=["Test rationale."],
    )


def test_eligible_event_passes() -> None:
    analysis = make_analysis(
        EventType.CONTRACT,
        80.0,
    )

    assert is_event_eligible(analysis) is True


def test_ineligible_event_type_fails() -> None:
    analysis = make_analysis(
        EventType.OTHER,
        90.0,
    )

    assert is_event_eligible(analysis) is False


def test_low_score_event_fails() -> None:
    analysis = make_analysis(
        EventType.CONTRACT,
        40.0,
    )

    assert is_event_eligible(analysis) is False


def test_select_top_eligible_event_skips_ineligible_items() -> None:
    analyses = [
        make_analysis(EventType.OTHER, 95.0),
        make_analysis(EventType.CONTRACT, 75.0),
        make_analysis(EventType.PRODUCT, 65.0),
    ]

    selected = select_top_eligible_event(analyses)

    assert selected is analyses[1]

def test_commentary_is_not_eligible() -> None:
    analysis = make_analysis(
        EventType.CONTRACT,
        90.0,
        article_kind=ArticleKind.VALUATION_COMMENTARY,
        is_primary_event=False,
    )

    assert is_event_eligible(analysis) is False

def test_valuation_headline_is_vetoed_even_if_llm_calls_it_primary() -> None:
    analysis = make_analysis(
        EventType.CONTRACT,
        90.0,
        article_kind=ArticleKind.CORPORATE_EVENT,
        is_primary_event=True,
    )

    analysis.cluster.title = (
        "Rocket Lab may be 38% undervalued after contract wins"
    )

    assert is_event_eligible(analysis) is False