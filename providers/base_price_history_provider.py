from abc import ABC, abstractmethod

from models.stock import Stock


class BasePriceHistoryProvider(ABC):
    @abstractmethod
    def fetch_daily_closes(
        self,
        stock: Stock,
        days: int = 365,
    ) -> list[float]:
        raise NotImplementedError