from agents.iqa_agent import IQAAgent
from models.enums import Recommendation
from models.research_report import ResearchReport
from models.stock import Stock


def make_report(
    recommendation: Recommendation,
    confidence: float,
) -> ResearchReport:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    return ResearchReport(
        stock=stock,
        summary="Rocket Lab won a new government contract.",
        strengths=["Meaningful corporate event detected"],
        risks=["Financial impact has not yet been verified"],
        recommendation=recommendation,
        confidence=confidence,
    )


def test_iqa_passes_valid_research_report() -> None:
    iqa = IQAAgent()

    report = make_report(
        recommendation=Recommendation.RESEARCH,
        confidence=90.0,
    )

    passed, issues = iqa.review(report)

    assert passed is True
    assert issues == []


def test_iqa_rejects_low_confidence_buy() -> None:
    iqa = IQAAgent()

    report = make_report(
        recommendation=Recommendation.BUY,
        confidence=50.0,
    )

    passed, issues = iqa.review(report)

    assert passed is False
    assert "BUY recommendation requires confidence of at least 70." in issues