from models.event_analysis import EventAnalysis, EventType


ELIGIBLE_EVENT_TYPES = {
    EventType.CONTRACT,
    EventType.EARNINGS,
    EventType.ACQUISITION,
    EventType.PRODUCT,
}


def is_event_eligible(
    analysis: EventAnalysis,
    minimum_opportunity_score: float = 50.0,
) -> bool:
    if not analysis.is_primary_event:
        return False

    if analysis.event_type not in ELIGIBLE_EVENT_TYPES:
        return False

    if analysis.opportunity_score < minimum_opportunity_score:
        return False

    return True


def select_top_eligible_event(
    analyses: list[EventAnalysis],
    minimum_opportunity_score: float = 50.0,
) -> EventAnalysis | None:
    for analysis in analyses:
        if is_event_eligible(
            analysis,
            minimum_opportunity_score=minimum_opportunity_score,
        ):
            return analysis

    return None
    