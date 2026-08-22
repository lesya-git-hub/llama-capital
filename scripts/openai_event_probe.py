from models.evidence import Evidence
from models.event_cluster import EventCluster
from models.stock import Stock
from providers.openai_event_provider import OpenAIEventProvider

def main() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    evidence = Evidence(
        stock=stock,
        source="Benzinga",
        headline=(
            "Rocket Lab wins new Space Force contract "
            "worth $12 million"
        ),
        content="",
        url="https://example.com",
    )

    cluster = EventCluster(
        stock=stock,
        title=evidence.headline,
        evidence_items=[evidence],
    )

    provider = OpenAIEventProvider()

    result = provider.analyze(cluster)

    print("Event type:", result.event_type.value)
    print("Impact:", result.impact_direction.value)
    print("Impact score:", result.impact_score)
    print("Materiality:", result.materiality_score)
    print("Summary:", result.summary)

    print("Bull case:")
    for item in result.bull_case:
        print("-", item)

    print("Bear case:")
    for item in result.bear_case:
        print("-", item)

    print("Uncertainties:")
    for item in result.uncertainties:
        print("-", item)

        print("Rationale:", result.rationale)

if __name__ == "__main__":
    main()