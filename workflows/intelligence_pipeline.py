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
        corroboration_provider=None,
        evidence_matcher=None,
    ) -> None:
        self.evidence_provider = (
            evidence_provider
            or FinnhubEvidenceProvider()
        )

        self.corroboration_provider = corroboration_provider
        self.evidence_matcher = evidence_matcher

        if clusterer is not None:
            self.clusterer = clusterer
        else:
            from tools.event_clusterer import SemanticEventClusterer

            self.clusterer = SemanticEventClusterer(
                threshold=0.60,
            )

    def _enrich_clusters(
        self,
        clusters,
        corroborating_evidence,
    ) -> None:
        if self.evidence_matcher is None:
            return

        for cluster in clusters:
            matched_urls = {
                item.url
                for item in cluster.evidence_items
            }

            for official_item in corroborating_evidence:
                if official_item.url in matched_urls:
                    continue

                is_match = any(
                    self.evidence_matcher.matches(
                        news_item,
                        official_item,
                    )
                    for news_item in cluster.evidence_items
                )

                if is_match:
                    cluster.evidence_items.append(
                        official_item
                    )
                    matched_urls.add(
                        official_item.url
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

        if (
            self.corroboration_provider is not None
            and self.evidence_matcher is not None
        ):
            corroborating_evidence = (
                self.corroboration_provider.fetch(stock)
            )

            self._enrich_clusters(
                clusters,
                corroborating_evidence,
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