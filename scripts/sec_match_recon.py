from models.stock import Stock
from models.evidence import Evidence
from tools.evidence_filter import filter_evidence
from providers.finnhub_evidence_provider import (
    FinnhubEvidenceProvider,
)
from providers.sec_evidence_provider import (
    SECEvidenceProvider,
)
from tools.evidence_matcher import EvidenceMatcher


def main() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    finnhub = FinnhubEvidenceProvider()
    sec = SECEvidenceProvider()
    matcher = EvidenceMatcher()

    news_items = finnhub.fetch(stock)

    news_items = filter_evidence(
        news_items,
        max_items=10,
    )
    sec_items = sec.fetch(stock)

    print("News:", len(news_items))
    print("SEC:", len(sec_items))

    for news in news_items[:10]:
        print()
        print("=" * 100)
        print("NEWS:", news.headline)

        matches = []

        for filing in sec_items:
            score = matcher.similarity(
                news,
                filing,
            )

            matches.append(
                (
                    score,
                    filing,
                )
            )

        matches.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        for score, filing in matches[:3]:
            matched = matcher.matches(
                news,
                filing,
            )

            print(
                f"{score:.3f}",
                "| MATCH:" if matched else "| no match:",
                filing.headline,
            )

    print()
    print("=" * 100)
    print("CONTROLLED TRUE-POSITIVE TEST")
    print("=" * 100)

    test_news = Evidence(
        stock=stock,
        source="Reuters",
        headline=(
            "Rocket Lab enters agreement to acquire "
            "Iridium Communications"
        ),
        content=(
            "Rocket Lab entered into a merger agreement "
            "with Iridium Communications."
        ),
        url="https://example.com/test",
    )

    for filing in sec_items:
        score = matcher.similarity(
            test_news,
            filing,
        )

        matched = matcher.matches(
            test_news,
            filing,
        )

        if matched:
            print(
                f"{score:.3f}",
                "| MATCH:",
                filing.headline,
            )


if __name__ == "__main__":
    main()