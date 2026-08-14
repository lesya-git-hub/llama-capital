from models.committee_decision import CommitteeDecision
from models.research_report import ResearchReport
from models.screening_result import ScreeningResult
from models.enums import CommitteeDecisionType

class CommitteeAgent:

    def decide(
        self,
        screening: ScreeningResult,
        research: ResearchReport,
        qa_passed: bool,
        iqa_passed: bool,
    ) -> CommitteeDecision:

        rationale = []
        if not qa_passed:
            rationale.append("QA rejected the research report.")

            return CommitteeDecision(
                stock=research.stock,
                decision=CommitteeDecisionType.REJECT,
                allocation_percent=0.0,
                confidence=0.0,
                rationale=rationale,
        )

        if not iqa_passed:
            rationale.append("iQA rejected the research report.")

            return CommitteeDecision(
                stock=research.stock,
                decision=CommitteeDecisionType.REJECT,
                allocation_percent=0.0,
                confidence=0.0,
                rationale=rationale,
            )

        if screening.passed:
            rationale.append("Universe Screener approved the company.")

        rationale.append(
            f"Research confidence: {research.confidence}"
        )

        if screening.score >= 80 and research.confidence >= 80:
            decision = CommitteeDecisionType.BUY
            allocation = 60.0

        elif screening.score >= 70:
            decision = CommitteeDecisionType.WATCHLIST
            allocation = 0.0

        else:
            decision = CommitteeDecisionType.REJECT
            allocation = 0.0

        return CommitteeDecision(
            stock=research.stock,
            decision=decision,
            allocation_percent=allocation,
            confidence=(screening.score + research.confidence) / 2,
            rationale=rationale,
        )