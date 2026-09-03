from models.evidence import Evidence
from models.stock import Stock
from tools.stock_evidence_relevance import (
    StockEvidenceRelevanceFilter,
)


def make_stock() -> Stock:
    return Stock(
        ticker="FTNT",
        company="FORTINET INC",
        sector="Technology",
        industry="Cybersecurity",
        exchange="NASDAQ",
    )


def make_evidence(
    headline: str,
) -> Evidence:
    return Evidence(
        stock=make_stock(),
        source="Yahoo",
        headline=headline,
        content="",
        url="https://example.com",
    )


def test_relevant_ticker_passes() -> None:
    relevance_filter = (
        StockEvidenceRelevanceFilter()
    )

    evidence = make_evidence(
        "Fortinet (FTNT) Reports Strong Growth"
    )

    assert relevance_filter.is_relevant(
        make_stock(),
        evidence,
    )


def test_relevant_company_name_passes() -> None:
    relevance_filter = (
        StockEvidenceRelevanceFilter()
    )

    evidence = make_evidence(
        "Fortinet Launches New Security Product"
    )

    assert relevance_filter.is_relevant(
        make_stock(),
        evidence,
    )


def test_unrelated_company_fails() -> None:
    relevance_filter = (
        StockEvidenceRelevanceFilter()
    )

    evidence = make_evidence(
        "Zscaler to Report Q4 Earnings"
    )

    assert not relevance_filter.is_relevant(
        make_stock(),
        evidence,
    )


def test_filter_removes_unrelated_evidence() -> None:
    relevance_filter = (
        StockEvidenceRelevanceFilter()
    )

    evidence_items = [
        make_evidence(
            "Fortinet Launches New Security Product"
        ),
        make_evidence(
            "Zscaler to Report Q4 Earnings"
        ),
        make_evidence(
            "Buy Palo Alto Networks Stock?"
        ),
    ]

    result = relevance_filter.filter(
        make_stock(),
        evidence_items,
    )

    assert len(result) == 1
    assert (
        result[0].headline
        == "Fortinet Launches New Security Product"
    )