from models.event_analysis import EventAnalysis
from models.stock import Stock
from providers.finnhub_evidence_provider import FinnhubEvidenceProvider
from tools.evidence_filter import filter_evidence
from tools.event_scorer import analyze_event


class IntelligencePipeline:
    def __init__(
        self,
        evidence_provider=None,
        clusterer=None,
    ) -> None:
        self.evidence_provider = (
            evidence_provider
            or FinnhubEvidenceProvider()
        )

        if clusterer is not None:
            self.clusterer = clusterer
        else:
            from tools.event_clusterer import SemanticEventClusterer

            self.clusterer = SemanticEventClusterer(
                threshold=0.60,
            )

    def run(
        self,
        stock: Stock,
        max_evidence: int = 10,
    ) -> list[EventAnalysis]:
        evidence = self.evidence_provider.fetch(stock)

        filtered_evidence = filter_evidence(
            evidence,
            max_items=max_evidence,
        )

        clusters = self.clusterer.cluster(
            filtered_evidence,
        )

        analyses = [
            analyze_event(cluster)
            for cluster in clusters
        ]

        return sorted(
            analyses,
            key=lambda analysis: analysis.opportunity_score,
            reverse=True,
        )