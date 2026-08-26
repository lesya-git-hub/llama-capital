from models.event_analysis import EventAnalysis, EventType
from models.event_cluster import EventCluster
from agents.event_analyst import EventAnalyst
from models.source_quality import SourceType
from tools.source_quality import (
    get_source_quality,
    get_source_type,
)

def calculate_source_quality(
    cluster: EventCluster,
) -> float:
    scores = [
        get_source_quality(item.source)
        for item in cluster.evidence_items
    ]

    if not scores:
        return 0.0

    return round(
        sum(scores) / len(scores),
        1,
    )


def calculate_corroboration(
    cluster: EventCluster,
) -> float:
    if not cluster.evidence_items:
        return 0.0

    source_types = {
        get_source_type(item.source)
        for item in cluster.evidence_items
    }

    unique_sources = {
        item.source
        for item in cluster.evidence_items
    }

    has_official = (
        SourceType.OFFICIAL in source_types
    )

    has_primary_news = (
        SourceType.PRIMARY_NEWS in source_types
    )

    has_secondary_news = (
        SourceType.SECONDARY_NEWS in source_types
    )

    independent_source_count = len(unique_sources)

    if has_official and has_primary_news:
        return 10.0

    if (
        has_official
        and independent_source_count >= 2
    ):
        return 9.0

    if (
        has_primary_news
        and independent_source_count >= 3
    ):
        return 8.5

    if (
        has_primary_news
        and independent_source_count >= 2
    ):
        return 7.5

    if (
        has_secondary_news
        and independent_source_count >= 3
    ):
        return 6.0

    if independent_source_count >= 2:
        return 5.0

    source_type = get_source_type(
        cluster.evidence_items[0].source
    )

    if source_type == SourceType.OFFICIAL:
        return 7.0

    if source_type == SourceType.PRIMARY_NEWS:
        return 6.0

    if source_type == SourceType.SECONDARY_NEWS:
        return 3.0

    if source_type == SourceType.COMMENTARY:
        return 1.5

    return 2.0


def calculate_strategic_relevance(
    cluster: EventCluster,
    event_type: EventType,
) -> float:
    text = " ".join(
        item.headline.lower()
        for item in cluster.evidence_items
    )

    score = 5.0

    high_relevance_terms = (
        "space force",
        "government",
        "military",
        "neutron",
        "acquisition",
        "contract",
        "production",
        "backlog",
    )

    for term in high_relevance_terms:
        if term in text:
            score += 0.75

    if event_type in {
        EventType.CONTRACT,
        EventType.ACQUISITION,
        EventType.GUIDANCE,
    }:
        score += 1.0

    return min(score, 10.0)


def analyze_event(
    cluster: EventCluster,
) -> EventAnalysis:
    analyst = EventAnalyst()

    llm_analysis = analyst.analyze(cluster)
    article_kind = llm_analysis.article_kind
    is_primary_event = llm_analysis.is_primary_event

    event_type = llm_analysis.event_type
    impact_direction = llm_analysis.impact_direction
    impact_score = llm_analysis.impact_score

    # importance = EVENT_IMPORTANCE[event_type]
    importance = llm_analysis.materiality_score
    source_quality = calculate_source_quality(cluster)
    corroboration = calculate_corroboration(cluster)
    strategic_relevance = calculate_strategic_relevance(
        cluster,
        event_type,
    )

    opportunity_score = (
        importance * 0.35
        + source_quality * 0.25
        + corroboration * 0.15
        + strategic_relevance * 0.25
    ) * 10

    rationale = [
        f"Event type: {event_type.value}",
        f"Importance score: {importance:.1f}",
        f"Source quality score: {source_quality:.1f}",
        f"Corroboration score: {corroboration:.1f}",
        f"Strategic relevance score: {strategic_relevance:.1f}",
        f"LLM materiality score: {llm_analysis.materiality_score:.1f}",
        f"LLM rationale: {llm_analysis.rationale}",
    ]

    return EventAnalysis(
        cluster=cluster,
        event_type=event_type,
        article_kind=article_kind,
        is_primary_event=is_primary_event,
        importance_score=importance,
        source_quality_score=source_quality,
        corroboration_score=corroboration,
        strategic_relevance_score=strategic_relevance,
        opportunity_score=round(opportunity_score, 1),
        rationale=rationale,
        impact_direction=impact_direction,
        impact_score=round(impact_score, 1),
    )