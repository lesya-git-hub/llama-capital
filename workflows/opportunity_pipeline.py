from agents.opportunity_agent import OpportunityAgent
from agents.qa_agent import QAAgent
from models.opportunity import Opportunity
from models.research_report import ResearchReport


class OpportunityPipeline:
    def __init__(self) -> None:
        self.opportunity_agent = OpportunityAgent()
        self.qa_agent = QAAgent()

    def run(
        self,
        opportunity: Opportunity,
    ) -> tuple[ResearchReport, bool, list[str]]:
        report = self.opportunity_agent.evaluate(opportunity)
        passed, issues = self.qa_agent.review(report)

        return report, passed, issues