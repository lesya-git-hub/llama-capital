from models.stock import Stock
from models.universe_config import UniverseConfig
from providers.base_universe_provider import (
    BaseUniverseProvider,
)


class ConfiguredUniverseProvider(
    BaseUniverseProvider
):
    def __init__(
        self,
        source_provider: BaseUniverseProvider,
        config: UniverseConfig,
    ) -> None:
        self.source_provider = source_provider
        self.config = config

    def fetch(self) -> list[Stock]:
        stocks = self.source_provider.fetch()

        allowed = {
            ticker.strip().upper()
            for ticker in self.config.allowed_tickers
        }

        if not allowed:
            return []

        selected = [
            stock
            for stock in stocks
            if stock.ticker.upper() in allowed
        ]

        return sorted(
            selected,
            key=lambda stock: stock.ticker,
        )[: self.config.max_candidates]