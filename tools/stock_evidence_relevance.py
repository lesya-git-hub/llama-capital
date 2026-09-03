from models.evidence import Evidence
from models.stock import Stock


class StockEvidenceRelevanceFilter:
    def is_relevant(
        self,
        stock: Stock,
        evidence: Evidence,
    ) -> bool:
        ticker = stock.ticker.upper()

        company_terms = self._company_terms(
            stock.company
        )

        headline = evidence.headline.upper()

        if ticker in headline:
            return True

        if any(
            term in headline
            for term in company_terms
        ):
            return True

        return False

    def filter(
        self,
        stock: Stock,
        evidence_items: list[Evidence],
    ) -> list[Evidence]:
        return [
            evidence
            for evidence in evidence_items
            if self.is_relevant(
                stock,
                evidence,
            )
        ]

    def _company_terms(
        self,
        company: str,
    ) -> set[str]:
        company = company.upper()

        removable_terms = {
            "INC",
            "CORP",
            "CORPORATION",
            "HOLDINGS",
            "LTD",
            "PLC",
            "CLASS",
        }

        words = {
            word.strip("-")
            for word in company.split()
            if len(word.strip("-")) >= 4
            and word.strip("-")
            not in removable_terms
        }

        return words