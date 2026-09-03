from models.screening_result import ScreeningResult
from models.stock import Stock
from workflows.shortlist_intelligence_pipeline import (
    ShortlistIntelligencePipeline,
)


def make_screening_result(
    ticker: str,
) -> ScreeningResult:
    stock = Stock(
        ticker=ticker,
        company=ticker,
        sector="Test",
        industry="Test",
        exchange="NASDAQ",
    )

    return ScreeningResult(
        stock=stock,
        passed=True,
        score=100.0,
        reasons=[],
    )


class FakeIntelligencePipeline:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(
        self,
        stock: Stock,
        *,
        max_evidence: int = 10,
    ) -> list:
        self.calls.append(stock.ticker)

        return []


def test_shortlist_candidates_are_sent_to_intelligence() -> None:
    intelligence_pipeline = (
        FakeIntelligencePipeline()
    )

    pipeline = ShortlistIntelligencePipeline(
        intelligence_pipeline=intelligence_pipeline,
    )

    candidates = [
        make_screening_result("AAA"),
        make_screening_result("BBB"),
        make_screening_result("CCC"),
    ]

    result = pipeline.run(
        candidates,
        max_evidence=5,
    )

    assert intelligence_pipeline.calls == [
        "AAA",
        "BBB",
        "CCC",
    ]

    assert set(
        result.analyses_by_ticker.keys()
    ) == {
        "AAA",
        "BBB",
        "CCC",
    }

    assert result.failures == []

def test_shortlist_intelligence_continues_after_failure() -> None:
    class FailingIntelligencePipeline(
        FakeIntelligencePipeline
    ):
        def run(
            self,
            stock: Stock,
            *,
            max_evidence: int = 10,
        ) -> list:
            self.calls.append(stock.ticker)

            if stock.ticker == "BBB":
                raise ValueError(
                    "Intelligence unavailable."
                )

            return []

    intelligence_pipeline = (
        FailingIntelligencePipeline()
    )

    pipeline = ShortlistIntelligencePipeline(
        intelligence_pipeline=intelligence_pipeline,
    )

    candidates = [
        make_screening_result("AAA"),
        make_screening_result("BBB"),
        make_screening_result("CCC"),
    ]

    result = pipeline.run(
        candidates,
        max_evidence=5,
    )

    assert set(
        result.analyses_by_ticker.keys()
    ) == {
        "AAA",
        "CCC",
    }

    assert len(result.failures) == 1
    assert result.failures[0].ticker == "BBB"
    assert (
        result.failures[0].reason
        == "Intelligence unavailable."
    )