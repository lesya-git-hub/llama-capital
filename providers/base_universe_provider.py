from abc import ABC, abstractmethod

from models.stock import Stock


class BaseUniverseProvider(ABC):
    @abstractmethod
    def fetch(self) -> list[Stock]:
        raise NotImplementedError