from models.opportunity import Opportunity


def calculate_opportunity_score(opportunity: Opportunity) -> float:
    score = 0.0

    # Event importance contributes directly
    score += opportunity.importance * 10

    # Reuters gets a credibility bonus
    if opportunity.source.lower() == "reuters":
        score += 10

    return min(score, 100)