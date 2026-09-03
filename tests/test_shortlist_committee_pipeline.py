from models.committee_candidate import (
    CommitteeCandidate,
)
from models.committee_decision import (
    CommitteeDecision,
)
from models.enums import CommitteeDecisionType
from models.research_report import ResearchReport
from models.screening_result import ScreeningResult
from models.stock import Stock
from workflows.shortlist_committee_pipeline import (
    ShortlistCommitteePipeline,
)


def make_stock(
    ticker: str,
) -> Stock:
    return Stock(
        ticker=ticker,
        company=ticker,
        sector="Test",
        industry="Test",
        exchange="NASDAQ",
    )


def make_candidate(
    ticker: str,
) -> CommitteeCandidate:
    stock = make_stock(ticker)

    screening = ScreeningResult(
        stock=stock,
        passed=True,
        score=100.0,
        reasons=[],
    )

    research = ResearchReport.model_construct(
        stock=stock,
    )

    return CommitteeCandidate(
        screening=screening,
        research=research,
        qa_passed=True,
        iqa_passed=True,
    )


class FakeCommitteeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def decide(
        self,
        screening,
        research,
        qa_passed,
        iqa_passed,
    ) -> CommitteeDecision:
        ticker = research.stock.ticker

        self.calls.append(ticker)

        confidence = {
            "AMD": 70.0,
            "CRWD": 90.0,
        }[ticker]

        allocation = {
            "AMD": 0.0,
            "CRWD": 60.0,
        }[ticker]

        decision = (
            CommitteeDecisionType.BUY
            if allocation > 0
            else CommitteeDecisionType.WATCHLIST
        )

        return CommitteeDecision(
            stock=research.stock,
            decision=decision,
            allocation_percent=allocation,
            confidence=confidence,
            rationale=[],
        )


def test_committee_processes_all_candidates() -> None:
    agent = FakeCommitteeAgent()

    pipeline = ShortlistCommitteePipeline(
        committee_agent=agent,
    )

    candidates = [
        make_candidate("AMD"),
        make_candidate("CRWD"),
    ]

    decisions = pipeline.run(
        candidates
    )

    assert agent.calls == [
        "AMD",
        "CRWD",
    ]

    assert len(decisions) == 2


def test_committee_ranks_stronger_decision_first() -> None:
    pipeline = ShortlistCommitteePipeline(
        committee_agent=FakeCommitteeAgent(),
    )

    candidates = [
        make_candidate("AMD"),
        make_candidate("CRWD"),
    ]

    decisions = pipeline.run(
        candidates
    )

    assert (
        decisions[0].stock.ticker
        == "CRWD"
    )

    assert (
        decisions[1].stock.ticker
        == "AMD"
    )