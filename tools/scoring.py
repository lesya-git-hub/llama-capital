from models.opportunity import Opportunity


def calculate_opportunity_score(
    opportunity: Opportunity,
) -> float:
    """
    Calculate research confidence from evidence quality
    and event significance.

    Impact direction is intentionally excluded:
    negative events can still be highly important
    research opportunities.
    """

    score = (
        opportunity.materiality_score * 3.0
        + opportunity.source_quality_score * 2.0
        + opportunity.corroboration_score * 2.0
        + opportunity.strategic_relevance_score * 3.0
    )

    return round(
        max(0.0, min(score, 100.0)),
        1,
    )