import re

from models.evidence import Evidence
from models.financial_claim import (
    FinancialClaim,
    FinancialClaimStatus,
    FinancialPeriod,
)


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

    @staticmethod
    def extract_financial_period(
        evidence: Evidence,
    ) -> tuple[str, str] | None:
        text = (
            f"{evidence.headline} "
            f"{evidence.content}"
        ).lower()

        quarter_patterns = {
            "Q1": (
                r"\bq1\s+(\d{4})\b",
                r"\bfirst quarter(?: of)?\s+(\d{4})\b",
            ),
            "Q2": (
                r"\bq2\s+(\d{4})\b",
                r"\bsecond quarter(?: of)?\s+(\d{4})\b",
            ),
            "Q3": (
                r"\bq3\s+(\d{4})\b",
                r"\bthird quarter(?: of)?\s+(\d{4})\b",
            ),
            "Q4": (
                r"\bq4\s+(\d{4})\b",
                r"\bfourth quarter(?: of)?\s+(\d{4})\b",
            ),
        }

        for quarter, patterns in quarter_patterns.items():
            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    return quarter, match.group(1)

        return None

    @staticmethod
    def extract_money_amounts(
        evidence: Evidence,
    ) -> set[tuple[float, str]]:
        text = (
            f"{evidence.headline} "
            f"{evidence.content}"
        ).lower()

        matches = re.findall(
            r"\$(\d+(?:\.\d+)?)\s*"
            r"(million|billion|m|b)\b",
            text,
        )

        normalized: set[tuple[float, str]] = set()

        for value, unit in matches:
            normalized_unit = (
                "million"
                if unit in {"million", "m"}
                else "billion"
            )

            normalized.add(
                (
                    float(value),
                    normalized_unit,
                )
            )

        return normalized

    def matches(
        self,
        first: Evidence,
        second: Evidence,
    ) -> bool:
        first_claims = self.extract_financial_claims(
            first
        )
        second_claims = self.extract_financial_claims(
            second
        )

        shared_metrics = (
            first_claims.keys()
            & second_claims.keys()
        )

        for metric in shared_metrics:
            if first_claims[metric].isdisjoint(
                second_claims[metric]
            ):
                return False

        first_period = self.extract_financial_period(
            first
        )
        second_period = self.extract_financial_period(
            second
        )

        if (
            first_period is not None
            and second_period is not None
            and first_period != second_period
        ):
            return False

        first_amounts = self.extract_money_amounts(
            first
        )
        second_amounts = self.extract_money_amounts(
            second
        )

        if (
            first_amounts
            and second_amounts
            and first_amounts.isdisjoint(second_amounts)
        ):
            return False

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

    @staticmethod
    def extract_structured_financial_claims(
        evidence: Evidence,
    ) -> list[FinancialClaim]:
        text = (
            f"{evidence.headline} "
            f"{evidence.content}"
        ).lower()

        claims: list[FinancialClaim] = []

        pattern = (
            r"(?:u\.s\.\s+)?commercial revenue"
            r"[^.!?]{0,100}?"
            r"\$(\d+(?:\.\d+)?)\s*"
            r"(million|billion|m|b)\b"
        )

        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            value, unit = match.groups()

            normalized_unit = (
                "million"
                if unit in {"million", "m"}
                else "billion"
            )

            claim_period = FinancialPeriod.UNKNOWN
            claim_year: int | None = None
            claim_quarter: int | None = None

            context_before = text[:match.start()]

            scope_matches = list(
                re.finditer(
                    (
                        r"\b(?:q([1-4])|(fy|full year))"
                        r"\s+(\d{4})\b"
                    ),
                    context_before,
                    flags=re.IGNORECASE,
                )
            )

            if scope_matches:
                scope_match = scope_matches[-1]

                quarter_value = scope_match.group(1)
                fiscal_year_value = scope_match.group(2)
                scope_year = int(scope_match.group(3))

                if quarter_value is not None:
                    claim_period = FinancialPeriod.QUARTER
                    claim_year = scope_year
                    claim_quarter = int(quarter_value)

                elif fiscal_year_value is not None:
                    claim_period = FinancialPeriod.FULL_YEAR
                    claim_year = scope_year
            # Recognise full-year claims without an explicit year.
            local_context = text[
                max(0, match.start() - 15):match.start()
            ]

            if re.search(r"\bfull year\s+$", local_context):
                claim_period = FinancialPeriod.FULL_YEAR
                claim_quarter = None
            claim_status = FinancialClaimStatus.ACTUAL

            scope_context = (
                context_before[scope_matches[-1].start():]
                if scope_matches
                else ""
            )

            claim_context = text[
                match.start():match.end()
            ]

            if (
                "we expect" in scope_context
                or "guidance" in scope_context
                or "outlook" in scope_context
                or "guidance" in claim_context
            ):
                claim_status = FinancialClaimStatus.GUIDANCE

            claims.append(
                FinancialClaim(
                    metric="commercial_revenue",
                    value=float(value),
                    unit=normalized_unit,
                    period=claim_period,
                    year=claim_year,
                    quarter=claim_quarter,
                    status=claim_status,
                )
            )

        return claims

    @staticmethod
    def extract_financial_claims(
        evidence: Evidence,
    ) -> dict[str, set[tuple[float, str]]]:
        structured_claims = (
            EvidenceMatcher
            .extract_structured_financial_claims(evidence)
        )

        document_period = (
            EvidenceMatcher.extract_financial_period(evidence)
        )

        claims: dict[
            str,
            set[tuple[float, str]],
        ] = {}

        for claim in structured_claims:
            if claim.status != FinancialClaimStatus.ACTUAL:
                continue

            if document_period is not None:
                quarter, year = document_period

                if claim.period != FinancialPeriod.QUARTER:
                    continue

                if claim.year != int(year):
                    continue

                if claim.quarter != int(quarter[1]):
                    continue

            claims.setdefault(
                claim.metric,
                set(),
            ).add(
                (claim.value, claim.unit)
            )

        return claims
