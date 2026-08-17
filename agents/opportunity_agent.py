from models.opportunity import Opportunity
from models.research_report import ResearchReport
from tools.scoring import calculate_opportunity_score
from models.enums import Recommendation

class OpportunityAgent:
    def evaluate(self, opportunity: Opportunity) -> ResearchReport:
        score = calculate_opportunity_score(opportunity)

        print(f"Evaluating: {opportunity.stock.ticker}")
        print(f"Event: {opportunity.event}")
        print(f"Importance: {opportunity.importance}")
        print(f"Score: {score}")

        return ResearchReport(
            stock=opportunity.stock,
            summary=(
                f"{opportunity.stock.company} was identified after the event: "
                f"{opportunity.event}."
            ),
            strengths=[
                "Meaningful corporate event detected",
                f"Source provided: {opportunity.evidence.source}",
            ],
            risks=[
                "Financial impact has not yet been verified",
                "Market reaction has not yet been measured",
            ],
            recommendation=Recommendation.RESEARCH,
            confidence=score,
        )