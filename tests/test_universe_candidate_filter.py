import pytest

from models.stock import Stock
from tools.universe_candidate_filter import (
    UniverseCandidateFilter,
)


def make_stock(ticker: str) -> Stock:
    return Stock(
        ticker=ticker,
        company=f"{ticker} Company",
        sector="Unknown",
        industry="Unknown",
        exchange="XNAS",
    )


def test_candidate_filter_limits_results() -> None:
    stocks = [
        make_stock("CCC"),
        make_stock("AAA"),
        make_stock("BBB"),
    ]

    candidate_filter = UniverseCandidateFilter(
        max_candidates=2,
    )

    results = candidate_filter.filter(stocks)

    assert [
        stock.ticker
        for stock in results
    ] == ["AAA", "BBB"]


def test_candidate_filter_removes_duplicates() -> None:
    stocks = [
        make_stock("AAA"),
        make_stock("AAA"),
        make_stock("BBB"),
    ]

    candidate_filter = UniverseCandidateFilter(
        max_candidates=10,
    )

    results = candidate_filter.filter(stocks)

    assert len(results) == 2


def test_candidate_filter_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        UniverseCandidateFilter(
            max_candidates=0,
        )