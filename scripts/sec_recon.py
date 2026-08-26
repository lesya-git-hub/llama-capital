from models.stock import Stock
from providers.sec_evidence_provider import SECEvidenceProvider


def main() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    provider = SECEvidenceProvider()

    evidence = provider.fetch(stock)

    print("SEC evidence found:", len(evidence))

    for item in evidence:
        print("-" * 100)
        print("Source:", item.source)
        print("Headline:", item.headline)
        print("URL:", item.url)
        print("Preview:", item.content[:500])


if __name__ == "__main__":
    main()