from models.event_analysis import EventAnalysis, EventType
from models.event_cluster import EventCluster
from tools.event_classifier import classify_event
from agents.event_analyst import EventAnalyst


SOURCE_QUALITY = {
    "Reuters": 10.0,
    "Bloomberg": 10.0,
    "Associated Press": 9.5,
    "Yahoo": 7.0,
    "Benzinga": 6.5,
    "SeekingAlpha": 5.5,
}


EVENT_IMPORTANCE = {
    EventType.CONTRACT: 8.0,
    EventType.EARNINGS: 8.0,
    EventType.GUIDANCE: 9.0,
    EventType.ACQUISITION: 9.0,
    EventType.PRODUCT: 7.5,
    EventType.REGULATORY: 8.5,
    EventType.PARTNERSHIP: 7.0,
    EventType.ANALYST_RATING: 5.5,
    EventType.FINANCING: 7.0,
    EventType.MANAGEMENT: 6.0,
    EventType.OTHER: 4.0,
}


def calculate_source_quality(cluster: EventCluster) -> float:
    scores = [
        SOURCE_QUALITY.get(item.source, 5.0)
        for item in cluster.evidence_items
    ]

    if not scores:
        return 0.0

    return sum(scores) / len(scores)


def calculate_corroboration(cluster: EventCluster) -> float:
    unique_sources = {
        item.source
        for item in cluster.evidence_items
    }

    source_count = len(unique_sources)

    if source_count >= 4:
        return 10.0

    if source_count == 3:
        return 8.0

    if source_count == 2:
        return 6.0

    if source_count == 1:
        return 3.0

    return 0.0


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
        importance_score=importance,
        source_quality_score=source_quality,
        corroboration_score=corroboration,
        strategic_relevance_score=strategic_relevance,
        opportunity_score=round(opportunity_score, 1),
        rationale=rationale,
        impact_direction=impact_direction,
        impact_score=round(impact_score, 1),
    )