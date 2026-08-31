from models.stock import Stock
from providers.base_universe_provider import (
    BaseUniverseProvider,
)


class MockUniverseProvider(BaseUniverseProvider):
    def fetch(self) -> list[Stock]:
        return [
            Stock(
                ticker="AAA",
                company="Alpha Aerospace",
                sector="Industrials",
                industry="Aerospace",
                exchange="NASDAQ",
            ),
            Stock(
                ticker="BBB",
                company="Beta Systems",
                sector="Technology",
                industry="Software",
                exchange="NYSE",
            ),
            Stock(
                ticker="CCC",
                company="Charlie Energy",
                sector="Energy",
                industry="Energy",
                exchange="NYSE",
            ),
        ]