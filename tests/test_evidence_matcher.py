from models.evidence import Evidence
from models.stock import Stock
from tools.evidence_matcher import EvidenceMatcher
from models.financial_claim import (
    FinancialClaimStatus,
    FinancialPeriod,
)

def make_evidence(
    headline: str,
    content: str,
    source: str = "Reuters",
) -> Evidence:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    return Evidence(
        stock=stock,
        source=source,
        headline=headline,
        content=content,
        url="https://example.com",
    )


def test_matching_event_with_shared_anchor_passes(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.75,
    )

    news = make_evidence(
        "Rocket Lab enters agreement to acquire Iridium",
        "Rocket Lab entered into a merger agreement with Iridium.",
    )

    filing = make_evidence(
        "Rocket Lab filed 8-K",
        "Rocket Lab entered into an Agreement and Plan of Merger "
        "with Iridium Communications.",
        source="SEC",
    )

    assert matcher.matches(
        news,
        filing,
    ) is True


def test_high_similarity_without_shared_anchor_fails(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.90,
    )

    news = make_evidence(
        "Rocket Lab stock may be undervalued",
        "Investors are discussing valuation.",
    )

    filing = make_evidence(
        "Rocket Lab filed 8-K",
        "The company entered into an equity distribution agreement.",
        source="SEC",
    )

    assert matcher.matches(
        news,
        filing,
    ) is False


def test_shared_anchor_below_threshold_fails(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.50,
    )

    news = make_evidence(
        "Rocket Lab acquisition of Iridium",
        "Rocket Lab plans to acquire Iridium.",
    )

    filing = make_evidence(
        "Rocket Lab filed merger 8-K",
        "Merger agreement with Iridium Communications.",
        source="SEC",
    )

    assert matcher.matches(
        news,
        filing,
    ) is False
def test_matches_when_relevant_chunk_exceeds_threshold(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "PLTR commercial revenue surges in Q2",
        "Palantir reported strong Q2 revenue growth.",
    )

    filing = make_evidence(
        "Palantir filed 8-K",
        (
            "General filing introduction and legal language. "
            "The company announced its financial results "
            "for the second quarter. "
            "Additional unrelated disclosure follows."
        ),
        source="SEC",
    )

    def fake_similarity(
        first: Evidence,
        second: Evidence,
    ) -> float:
        if (
            "financial results" 
            in second.content
        ):
            return 0.80

        return 0.30

    monkeypatch.setattr(
        matcher,
        "similarity",
        fake_similarity,
    )

    assert matcher.matches(
        news,
        filing,
    ) is True

def test_different_financial_periods_do_not_match(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 earnings",
        (
            "Palantir reported financial results "
            "for the second quarter of 2026."
        ),
    )

    filing = make_evidence(
        "Palantir Q1 2026 earnings",
        (
            "Palantir announced financial results "
            "for the first quarter of 2026."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.90,
    )

    assert matcher.matches(
        news,
        filing,
    ) is False
def test_same_financial_period_can_match(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 earnings",
        (
            "Palantir reported financial results "
            "for the second quarter of 2026."
        ),
    )

    filing = make_evidence(
        "Palantir Q2 2026 earnings",
        (
            "Palantir announced financial results "
            "for the second quarter of 2026."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.90,
    )

    assert matcher.matches(
        news,
        filing,
    ) is True

def test_conflicting_financial_amounts_do_not_match(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 commercial revenue",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $945 million."
        ),
    )

    filing = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $764 million."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.95,
    )

    assert matcher.matches(
        news,
        filing,
    ) is False
def test_matching_financial_amounts_can_match(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 commercial revenue",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $764 million."
        ),
    )

    filing = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $764 million."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.95,
    )

    assert matcher.matches(
        news,
        filing,
    ) is True

def test_matching_amount_survives_extra_sec_amounts(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 commercial revenue",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $764 million."
        ),
    )

    filing = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "Palantir reported financial results "
            "for Q2 2026. "
            "U.S. revenue was $1.573 billion. "
            "U.S. commercial revenue was $764 million. "
            "U.S. government revenue was $809 million. "
            "Total revenue was $1.935 billion."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.95,
    )

    assert matcher.matches(
        news,
        filing,
    ) is True

def test_same_amount_for_different_metric_does_not_match(
    monkeypatch,
) -> None:
    matcher = EvidenceMatcher.__new__(
        EvidenceMatcher
    )

    matcher.threshold = 0.65

    news = make_evidence(
        "Palantir Q2 2026 commercial revenue",
        (
            "Palantir reported Q2 2026 "
            "commercial revenue of $945 million."
        ),
    )

    filing = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "Palantir reported financial results "
            "for Q2 2026. "
            "U.S. commercial revenue was $764 million. "
            "Another financial metric was $945 million."
        ),
        source="SEC",
    )

    monkeypatch.setattr(
        matcher,
        "similarity",
        lambda first, second: 0.95,
    )

    assert matcher.matches(
        news,
        filing,
    ) is False

def test_extracts_commercial_revenue_amount_after_growth_text() -> None:
    evidence = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "U.S. commercial revenue grew 149% "
            "year-over-year and 28% "
            "quarter-over-quarter to $764 million."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (764.0, "million")
        }
    }
def test_commercial_revenue_claim_does_not_capture_later_amount() -> None:
    evidence = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "U.S. commercial revenue grew 149% "
            "year-over-year and 28% "
            "quarter-over-quarter to $764 million. "
            "Another financial metric later reached "
            "$3.424 billion."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (764.0, "million")
        }
    }
def test_commercial_revenue_claim_does_not_capture_unrelated_amount_from_second_occurrence() -> None:
    evidence = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "U.S. commercial revenue grew 149% "
            "year-over-year and 28% "
            "quarter-over-quarter to $764 million. "
            "U.S. commercial revenue continued to grow strongly. "
            "Total contract value reached $3.424 billion."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (764.0, "million")
        }
    }
def test_commercial_revenue_claim_does_not_cross_bullet_boundary() -> None:
    evidence = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "U.S. commercial revenue grew 149% "
            "year-over-year and 28% "
            "quarter-over-quarter to $764 million "
            "◦ U.S. government revenue grew 90% "
            "year-over-year "
            "• Total contract value reached "
            "$3.424 billion"
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (764.0, "million")
        }
    }
def test_commercial_revenue_claim_excludes_guidance() -> None:
    evidence = make_evidence(
        "Palantir Q2 2026 financial results",
        (
            "U.S. commercial revenue grew 149% "
            "year-over-year and 28% "
            "quarter-over-quarter to $764 million. "
            "U.S. commercial revenue guidance to "
            "in excess of $3.424 billion."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (764.0, "million")
        }
    }
def test_commercial_revenue_claim_distinguishes_quarter_from_full_year() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "U.S. commercial revenue grew 137% "
            "year-over-year and 28% "
            "quarter-over-quarter to $507 million. "
            "Full year U.S. commercial revenue grew "
            "109% year-over-year to $1.465 billion."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (507.0, "million")
        }
    }
def test_commercial_revenue_claim_excludes_full_year_outlook() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "Q4 2025 highlights: "
            "U.S. commercial revenue grew 137% "
            "year-over-year and 28% "
            "quarter-over-quarter to $507 million. "
            "For full year 2026, we expect: "
            "U.S. commercial revenue in excess of "
            "$3.144 billion."
        ),
        source="SEC",
    )

    claims = EvidenceMatcher.extract_financial_claims(
        evidence
    )

    assert claims == {
        "commercial_revenue": {
            (507.0, "million")
        }
    }
def test_extracts_structured_commercial_revenue_claim() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "U.S. commercial revenue grew 137% "
            "year-over-year and 28% "
            "quarter-over-quarter to $507 million."
        ),
        source="SEC",
    )

    claims = (
        EvidenceMatcher
        .extract_structured_financial_claims(evidence)
    )

    assert len(claims) == 1
    assert claims[0].metric == "commercial_revenue"
    assert claims[0].value == 507.0
    assert claims[0].unit == "million"
    assert claims[0].period == FinancialPeriod.QUARTER
    assert claims[0].year == 2025
    assert claims[0].quarter == 4
    assert claims[0].status == FinancialClaimStatus.ACTUAL

def test_structured_claim_identifies_q4_actual() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "Q4 2025 Highlights "
            "U.S. commercial revenue grew 137% "
            "year-over-year and 28% "
            "quarter-over-quarter to $507 million."
        ),
        source="SEC",
    )

    claims = (
        EvidenceMatcher
        .extract_structured_financial_claims(evidence)
    )

    assert len(claims) == 1

    claim = claims[0]

    assert claim.period == FinancialPeriod.QUARTER
    assert claim.year == 2025
    assert claim.quarter == 4
    assert claim.status == FinancialClaimStatus.ACTUAL
def test_structured_claim_distinguishes_q4_and_full_year_actuals() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "Q4 2025 Highlights "
            "U.S. commercial revenue grew 137% "
            "year-over-year to $507 million. "
            "FY 2025 Highlights "
            "U.S. commercial revenue grew 109% "
            "year-over-year to $1.465 billion."
        ),
        source="SEC",
    )

    claims = (
        EvidenceMatcher
        .extract_structured_financial_claims(evidence)
    )

    assert len(claims) == 2

    quarterly_claim = claims[0]
    full_year_claim = claims[1]

    assert quarterly_claim.period == FinancialPeriod.QUARTER
    assert quarterly_claim.year == 2025
    assert quarterly_claim.quarter == 4

    assert full_year_claim.period == FinancialPeriod.FULL_YEAR
    assert full_year_claim.year == 2025
    assert full_year_claim.quarter is None
    assert full_year_claim.status == FinancialClaimStatus.ACTUAL

def test_structured_claim_identifies_full_year_guidance() -> None:
    evidence = make_evidence(
        "Palantir Q4 2025 financial results",
        (
            "For full year 2026, we expect: "
            "U.S. commercial revenue in excess of "
            "$3.144 billion."
        ),
        source="SEC",
    )

    claims = (
        EvidenceMatcher
        .extract_structured_financial_claims(evidence)
    )

    assert len(claims) == 1

    claim = claims[0]

    assert claim.period == FinancialPeriod.FULL_YEAR
    assert claim.year == 2026
    assert claim.quarter is None
    assert claim.status == FinancialClaimStatus.GUIDANCE