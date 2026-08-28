from agents.iqa_agent import IQAAgent
from agents.opportunity_agent import OpportunityAgent
from agents.qa_agent import QAAgent
from models.opportunity import Opportunity
from models.research_report import ResearchReport
from exceptions.opportunity_exceptions import IneligibleOpportunityError

class OpportunityPipeline:
    def __init__(self) -> None:
        self.opportunity_agent = OpportunityAgent()
        self.qa_agent = QAAgent()
        self.iqa_agent = IQAAgent()

    def run(
        self,
        opportunity: Opportunity,
    ) -> tuple[
        ResearchReport,
        bool,
        list[str],
        bool,
        list[str],
    ]:  
        if not opportunity.eligible_for_research:
            raise IneligibleOpportunityError(
                "Ineligible opportunity reached research pipeline: "
                f"{opportunity.eligibility_reason}"
            )
        report = self.opportunity_agent.evaluate(opportunity)

        qa_passed, qa_issues = self.qa_agent.review(report)
        iqa_passed, iqa_issues = self.iqa_agent.review(report)

        return (
            report,
            qa_passed,
            qa_issues,
            iqa_passed,
            iqa_issues,
        )