from agents.committee_agent import CommitteeAgent
from models.committee_candidate import (
    CommitteeCandidate,
)
from models.committee_decision import (
    CommitteeDecision,
)


class ShortlistCommitteePipeline:
    def __init__(
        self,
        committee_agent=None,
    ) -> None:
        self.committee_agent = (
            committee_agent
            or CommitteeAgent()
        )

    def run(
        self,
        candidates: list[CommitteeCandidate],
    ) -> list[CommitteeDecision]:
        decisions: list[CommitteeDecision] = []

        for candidate in candidates:
            decision = self.committee_agent.decide(
                screening=candidate.screening,
                research=candidate.research,
                qa_passed=candidate.qa_passed,
                iqa_passed=candidate.iqa_passed,
            )

            decisions.append(decision)

        return sorted(
            decisions,
            key=lambda decision: (
                decision.allocation_percent,
                decision.confidence,
            ),
            reverse=True,
        )