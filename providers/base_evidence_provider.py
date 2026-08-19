from abc import ABC, abstractmethod

from models.evidence import Evidence
from models.stock import Stock


class BaseEvidenceProvider(ABC):
    @abstractmethod
    def fetch(self, stock: Stock) -> list[Evidence]:
        """Fetch evidence for a stock."""
        raise NotImplementedError