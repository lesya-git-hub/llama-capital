import pytest

from models.screening_result import ScreeningResult
from models.stock import Stock
from tools.universe_shortlister import UniverseShortlister


def make_result(
    ticker: str,
    score: float,
    passed: bool,
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
        passed=passed,
        score=score,
        reasons=[],
    )


def test_shortlist_keeps_only_passed_candidates() -> None:
    results = [
        make_result("AAA", 100.0, True),
        make_result("BBB", 95.0, False),
        make_result("CCC", 80.0, True),
    ]

    shortlist = UniverseShortlister().select(
        results
    )

    tickers = [
        result.stock.ticker
        for result in shortlist.candidates
    ]

    assert tickers == [
        "AAA",
        "CCC",
    ]


def test_shortlist_ranks_and_limits_candidates() -> None:
    results = [
        make_result("AAA", 80.0, True),
        make_result("BBB", 100.0, True),
        make_result("CCC", 90.0, True),
    ]

    shortlist = UniverseShortlister(
        max_candidates=2
    ).select(results)

    tickers = [
        result.stock.ticker
        for result in shortlist.candidates
    ]

    assert tickers == [
        "BBB",
        "CCC",
    ]


def test_shortlister_rejects_invalid_limit() -> None:
    with pytest.raises(
        ValueError,
        match="max_candidates",
    ):
        UniverseShortlister(
            max_candidates=0
        )
def test_shortlister_uses_ranking_score_to_break_score_ties():
    weaker = ScreeningResult(
        stock=Stock(
            ticker="WEAK",
            company="Weaker",
            sector="Test",
            industry="Test",
            exchange="Test",
        ),
        passed=True,
        score=100,
        ranking_score=20,
        reasons=[],
    )

    stronger = ScreeningResult(
        stock=Stock(
            ticker="STRONG",
            company="Stronger",
            sector="Test",
            industry="Test",
            exchange="Test",
        ),
        passed=True,
        score=100,
        ranking_score=50,
        reasons=[],
    )

    shortlist = UniverseShortlister(
        max_candidates=1
    ).select(
        [weaker, stronger]
    )

    assert (
        shortlist.candidates[0].stock.ticker
        == "STRONG"
    )