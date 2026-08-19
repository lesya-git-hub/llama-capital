from models.event_analysis import EventType
from models.event_cluster import EventCluster


def classify_event(cluster: EventCluster) -> EventType:
    text = " ".join(
        item.headline.lower()
        for item in cluster.evidence_items
    )

    if any(
        term in text
        for term in (
            "contract",
            "awarded",
            "delivery order",
            "space force",
        )
    ):
        return EventType.CONTRACT

    if any(
        term in text
        for term in (
            "earnings",
            "revenue",
            "quarter",
            "q1",
            "q2",
            "q3",
            "q4",
        )
    ):
        return EventType.EARNINGS

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
            "launch",
            "engine",
            "production",
            "neutron",
            "archimedes",
        )
    ):
        return EventType.PRODUCT

    if any(
        term in text
        for term in (
            "upgrade",
            "downgrade",
            "price target",
            "analyst",
            "bank of america",
        )
    ):
        return EventType.ANALYST_RATING

    return EventType.OTHER