from agents.qa_agent import QAAgent
from models.research_report import ResearchReport
from models.stock import Stock
from models.enums import Recommendation


def make_report(recommendation: Recommendation) -> ResearchReport:
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
        confidence=90.0,
    )


def test_valid_recommendation_passes() -> None:
    qa = QAAgent()
    report = make_report(Recommendation.RESEARCH)

    passed, issues = qa.review(report)

    assert passed is True
    assert issues == []


from models.enums import Recommendation


def test_missing_risks_fails() -> None:
    qa = QAAgent()

    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    report = ResearchReport(
        stock=stock,
        summary="Rocket Lab won a new government contract.",
        strengths=["Meaningful corporate event detected"],
        risks=[],
        recommendation=Recommendation.RESEARCH,
        confidence=90.0,
    )

    passed, issues = qa.review(report)

    assert passed is False
    assert "Missing risks." in issues
