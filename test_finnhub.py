from models.stock import Stock
from providers.finnhub_evidence_provider import FinnhubEvidenceProvider
from tools.evidence_filter import filter_evidence
from tools.event_clusterer import SemanticEventClusterer
from tools.event_scorer import analyze_event


stock = Stock(
    ticker="RKLB",
    company="Rocket Lab",
    sector="Industrials",
    industry="Aerospace",
    exchange="NASDAQ",
)

provider = FinnhubEvidenceProvider()

evidence = provider.fetch(stock)
filtered_evidence = filter_evidence(
    evidence,
    max_items=10,
)

print("Evidence found:", len(evidence))
print("Evidence selected:", len(filtered_evidence))
for item in filtered_evidence:
    print("-" * 100)
    print("Source:", item.source)
    print("Headline:", item.headline)
    print("URL:", item.url)
    print("-" * 100)

clusterer = SemanticEventClusterer(
    threshold=0.60,
)

clusters = clusterer.cluster(filtered_evidence)
analyses = [
    analyze_event(cluster)
    for cluster in clusters
]

analyses = sorted(
    analyses,
    key=lambda analysis: analysis.opportunity_score,
    reverse=True,
)

print()
print("Event clusters:", len(clusters))

for cluster in clusters:
    print("=" * 100)
    print("EVENT:", cluster.title)
    print("Evidence items:", len(cluster.evidence_items))

    for item in cluster.evidence_items:
        print("-", item.source, "|", item.headline)
print()
print("=" * 100)
print("RANKED OPPORTUNITIES")
print("=" * 100)

for rank, analysis in enumerate(analyses, start=1):
    print()
    print(f"#{rank}")
    print("Event:", analysis.cluster.title)
    print("Type:", analysis.event_type.value)
    print("Impact:", analysis.impact_direction.value)
    print("Impact score:", analysis.impact_score)
    print("Opportunity score:", analysis.opportunity_score)

    for reason in analysis.rationale:
        print("-", reason)