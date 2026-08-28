from abc import ABC, abstractmethod

from models.market_snapshot import MarketSnapshot
from models.stock import Stock


class BaseMarketDataProvider(ABC):
    @abstractmethod
    def fetch(
        self,
        stock: Stock,
    ) -> MarketSnapshot:
        raise NotImplementedError