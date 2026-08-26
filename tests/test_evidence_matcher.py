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