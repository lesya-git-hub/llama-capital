import re

from sentence_transformers import SentenceTransformer

from models.event_cluster import EventCluster
from models.evidence import Evidence


class SemanticEventClusterer:
    def __init__(
        self,
        model=None,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        threshold: float = 0.60,
    ) -> None:
        if model is not None:
            self.model = model
        else:
            self.model = SentenceTransformer(
                model_name
            )

        self.threshold = threshold

    @staticmethod
    def extract_event_groups(text: str) -> dict[str, set[str]]:
        text_lower = text.lower()

        groups: dict[str, set[str]] = {
            "contract": set(),
            "product": set(),
            "earnings": set(),
            "acquisition": set(),
            "analyst": set(),
            }

        contract_terms = {
            "space force",
            "nite-star",
            "sdn-b",
            "contract",
            "awarded",
            "delivery orders",
            }

        product_terms = {
        "neutron",
        "archimedes",
        "hungry hippo",
        "engine",
        "launch",
        }

        earnings_terms = {
        "earnings",
        "revenue",
        "record q1",
        "record q2",
        "record q3",
        "record q4",
        }

        acquisition_terms = {
        "acquisition",
        "acquires",
        "merger",
        "iridium",
        }

        analyst_terms = {
        "bank of america",
        "goldman",
        "upgrade",
        "downgrade",
        "price target",
        "outlook",
        }

        mappings = {
        "contract": contract_terms,
        "product": product_terms,
        "earnings": earnings_terms,
        "acquisition": acquisition_terms,
        "analyst": analyst_terms,
        }

        for group_name, terms in mappings.items():
            for term in terms:
                if term in text_lower:
                    groups[group_name].add(term)

        money = re.findall(
            r"\$\s?\d+(?:\.\d+)?\s?(?:m|b|million|billion)",
            text_lower,
        )

        groups["contract"].update(money)

        return {
            group: values
            for group, values in groups.items()
            if values
        }


    def anchors_compatible(
        self,
        first: str,
        second: str,
    ) -> bool:
        first_groups = self.extract_event_groups(first)
        second_groups = self.extract_event_groups(second)

        if not first_groups and not second_groups:
            return True

        if not first_groups or not second_groups:
            return False

        # A headline touching several event categories is probably
        # a roundup article. Keep it isolated rather than allowing
        # it to bridge unrelated events together.
        if len(first_groups) > 1 or len(second_groups) > 1:
            return False

        first_category = next(iter(first_groups))
        second_category = next(iter(second_groups))

        if first_category != second_category:
            return False

        return True

    def cluster(
        self,
        evidence_items: list[Evidence],
    ) -> list[EventCluster]:
        if not evidence_items:
            return []

        headlines = [
            item.headline
            for item in evidence_items
        ]

        embeddings = self.model.encode(headlines)

        similarities = self.model.similarity(
            embeddings,
            embeddings,
        )

        clusters: list[EventCluster] = []
        assigned: set[int] = set()

        for index, item in enumerate(evidence_items):
            if index in assigned:
                continue

            cluster_items = [item]
            assigned.add(index)

            for other_index in range(
                index + 1,
                len(evidence_items),
            ):
                if other_index in assigned:
                    continue

                other_item = evidence_items[other_index]

                semantic_score = float(
                    similarities[index][other_index]
                )

                anchors_match = self.anchors_compatible(
                    item.headline,
                    other_item.headline,
                )

                if (
                    semantic_score >= self.threshold
                    and anchors_match
                ):
                    cluster_items.append(other_item)
                    assigned.add(other_index)

            clusters.append(
                EventCluster(
                    stock=item.stock,
                    title=item.headline,
                    evidence_items=cluster_items,
                )
            )

        return clusters