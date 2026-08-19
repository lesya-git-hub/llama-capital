from models.evidence import Evidence
from models.stock import Stock
from providers.base_evidence_provider import BaseEvidenceProvider

class MockEvidenceProvider(BaseEvidenceProvider):
    def fetch(self, stock: Stock) -> list[Evidence]:
        return [
            Evidence(
                stock=stock,
                source="Reuters",
                headline="Rocket Lab wins new government contract",
                content=(
                    "Rocket Lab announced that it won a new "
                    "government contract."
                ),
                url="https://example.com/mock-rklb-contract",
            )
        ]