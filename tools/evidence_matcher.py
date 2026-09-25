import re

from models.evidence import Evidence


class EvidenceMatcher:
    def __init__(
        self,
        model=None,
        model_name: str = (
            "sentence-transformers/all-MiniLM-L6-v2"
        ),
        threshold: float = 0.65,
    ) -> None:
        if model is not None:
            self.model = model
        else:
            from sentence_transformers import (
                SentenceTransformer,
            )

            self.model = SentenceTransformer(
                model_name
            )

        self.threshold = threshold

    @staticmethod
    def extract_anchors(text: str) -> set[str]:
        text = text.lower()

        anchors: set[str] = set()
        if any(
            term in text
            for term in (
                "earnings",
                "revenue",
                "financial results",
                "results of operations",
            )
        ):
            anchors.add("financial_results")

        terms = {
            "iridium",
            "neutron",
            "archimedes",
            "space force",
            "sdn-b",
            "nite-star",
            "merger",
            "acquisition",
            "equity distribution",
            "chief accounting officer",
            "financial results",
            "results of operations",
        }

        for term in terms:
            if term in text:
                anchors.add(term)

        money = re.findall(
            r"\$\s?\d+(?:\.\d+)?\s?"
            r"(?:m|b|million|billion)",
            text,
        )

        anchors.update(money)

        return anchors

    def anchors_compatible(
        self,
        first: Evidence,
        second: Evidence,
    ) -> bool:
        first_text = (
            f"{first.headline} "
            f"{first.content or ''}"
        )

        second_text = (
            f"{second.headline} "
            f"{second.content or ''}"
        )

        first_anchors = self.extract_anchors(first_text)
        second_anchors = self.extract_anchors(second_text)

        if not first_anchors or not second_anchors:
            return False

        return bool(
            first_anchors & second_anchors
        )

    def similarity(
        self,
        first: Evidence,
        second: Evidence,
    ) -> float:
        first_text = (
            f"{first.headline} "
            f"{first.content or ''}"
        )

        second_text = (
            f"{second.headline} "
            f"{second.content or ''}"
        )

        embeddings = self.model.encode(
            [
                first_text,
                second_text,
            ]
        )

        similarities = self.model.similarity(
            embeddings,
            embeddings,
        )

        return float(similarities[0][1])
    
    @staticmethod
    def chunk_evidence(
        evidence: Evidence,
    ) -> list[Evidence]:
        sentences = re.split(
            r"(?<=[.!?])\s+",
            evidence.content or "",
        )

        chunks: list[Evidence] = []

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            chunks.append(
                Evidence(
                    stock=evidence.stock,
                    source=evidence.source,
                    headline=evidence.headline,
                    content=sentence,
                    url=evidence.url,
                )
            )

        return chunks

    def matches(
        self,
        first: Evidence,
        second: Evidence,
    ) -> bool:
        if not self.anchors_compatible(
            first,
            second,
        ):
            return False

        chunks = self.chunk_evidence(second)

        for chunk in chunks:
            if not self.anchors_compatible(
                first,
                chunk,
            ):
                continue

            if (
                self.similarity(first, chunk)
                >= self.threshold
            ):
                return True

        return False