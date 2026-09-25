from models.event_analysis import EventAnalysis, EventType
from models.source_quality import SourceType
from tools.source_quality import get_source_type

ELIGIBLE_EVENT_TYPES = {
    EventType.CONTRACT,
    EventType.EARNINGS,
    EventType.ACQUISITION,
    EventType.PRODUCT,
}
VALUATION_COMMENTARY_TERMS = (
    "undervalued",
    "overvalued",
    "fair value",
    "fairly valued",
    "intrinsic value",
    "times revenue",
    "times earnings",
    "valuation",
)
def has_sufficient_evidence(
    analysis: EventAnalysis,
) -> bool:
    source_types = {
        get_source_type(item.source)
        for item in analysis.cluster.evidence_items
    }

    if SourceType.OFFICIAL in source_types:
        return True

    if SourceType.PRIMARY_NEWS in source_types:
        return True

    secondary_sources = {
        item.source
        for item in analysis.cluster.evidence_items
        if get_source_type(item.source)
        == SourceType.SECONDARY_NEWS
    }

    return len(secondary_sources) >= 2


def get_event_eligibility_reason(
    analysis: EventAnalysis,
    minimum_opportunity_score: float = 50.0,
) -> tuple[bool, str]:
    if has_commentary_veto(analysis):
        return False, "valuation commentary veto"

    if not analysis.is_primary_event:
        return False, "not a primary corporate event"

    if analysis.event_type not in ELIGIBLE_EVENT_TYPES:
        return False, "event type is not eligible"

    if not has_sufficient_evidence(analysis):
        return False, "insufficient evidence grounding"

    if analysis.opportunity_score < minimum_opportunity_score:
        return (
            False,
            (
                "opportunity score below threshold "
                f"({analysis.opportunity_score:.1f} < "
                f"{minimum_opportunity_score:.1f})"
            ),
        )

    return True, "eligible for research"

def is_event_eligible(
    analysis: EventAnalysis,
    minimum_opportunity_score: float = 50.0,
) -> bool:
    eligible, _ = get_event_eligibility_reason(
        analysis,
        minimum_opportunity_score=minimum_opportunity_score,
    )

    return eligible

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

def has_commentary_veto(
    analysis: EventAnalysis,
) -> bool:
    text = analysis.cluster.title.lower()

    return any(
        term in text
        for term in VALUATION_COMMENTARY_TERMS
    )