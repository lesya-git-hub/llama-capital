from models.event_analysis import (
    ArticleKind,
    EventType,
    ImpactDirection,
)
from models.event_analyst_output import EventAnalystOutput
from models.event_cluster import EventCluster
from providers.openai_event_provider import OpenAIEventProvider


class EventAnalyst:
    def __init__(self) -> None:
        self.llm_provider = OpenAIEventProvider()

    def analyze(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        try:
            return self.llm_provider.analyze(cluster)

        except Exception as error:
            print(
                "LLM Event Analyst failed. "
                f"Using deterministic fallback: {error}"
            )

            return self._fallback_analysis(cluster)

    def _fallback_analysis(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        event_type = self._fallback_event_type(cluster)

        impact_direction, impact_score = (
            self._fallback_impact(cluster)
        )

        return EventAnalystOutput(
            event_type=event_type,
            article_kind=ArticleKind.CORPORATE_EVENT,
            is_primary_event=True,
            impact_direction=impact_direction,
            impact_score=impact_score,
            materiality_score=5.0,
            summary=cluster.title,
            bull_case=[
                "Potential positive implications require further research."
            ],
            bear_case=[
                "Financial impact has not been independently verified."
            ],
            uncertainties=[
                "LLM analysis was unavailable.",
            ],
            rationale=(
                "Deterministic fallback analysis was used."
            ),
        )

    def _fallback_event_type(
        self,
        cluster: EventCluster,
    ) -> EventType:
        text = " ".join(
            item.headline.lower()
            for item in cluster.evidence_items
        )

        if any(
            term in text
            for term in (
                "contract",
                "awarded",
                "space force",
            )
        ):
            return EventType.CONTRACT

        if any(
            term in text
            for term in (
                "acquisition",
                "acquire",
                "merger",
            )
        ):
            return EventType.ACQUISITION

        if any(
            term in text
            for term in (
                "earnings",
                "revenue",
                "quarter",
            )
        ):
            return EventType.EARNINGS

        if any(
            term in text
            for term in (
                "launch",
                "engine",
                "production",
                "neutron",
            )
        ):
            return EventType.PRODUCT

        return EventType.OTHER

    def _fallback_impact(
        self,
        cluster: EventCluster,
    ) -> tuple[ImpactDirection, float]:
        text = " ".join(
            item.headline.lower()
            for item in cluster.evidence_items
        )

        positive_terms = (
            "wins",
            "awarded",
            "record",
            "approval",
            "clears",
            "growth",
            "production",
        )

        negative_terms = (
            "delay",
            "delayed",
            "miss",
            "downgrade",
            "decline",
            "loss",
        )

        positive_hits = sum(
            term in text
            for term in positive_terms
        )

        negative_hits = sum(
            term in text
            for term in negative_terms
        )

        if positive_hits > negative_hits:
            return ImpactDirection.POSITIVE, 5.0

        if negative_hits > positive_hits:
            return ImpactDirection.NEGATIVE, -5.0

        if positive_hits and negative_hits:
            return ImpactDirection.MIXED, 0.0

        return ImpactDirection.NEUTRAL, 0.0