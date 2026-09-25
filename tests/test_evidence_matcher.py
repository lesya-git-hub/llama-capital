from models.evidence import Evidence
from models.stock import Stock
from tools.evidence_matcher import EvidenceMatcher


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