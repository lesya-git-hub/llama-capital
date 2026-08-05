from agents.qa_agent import QAAgent
from models.research_report import ResearchReport
from models.stock import Stock


def make_report(recommendation: str) -> ResearchReport:
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
    report = make_report("RESEARCH")

    passed, issues = qa.review(report)

    assert passed is True
    assert issues == []


def test_invalid_recommendation_fails() -> None:
    qa = QAAgent()
    report = make_report("ATTACK_THE_MARKET")

    passed, issues = qa.review(report)

    assert passed is False
    assert "Invalid recommendation." in issues