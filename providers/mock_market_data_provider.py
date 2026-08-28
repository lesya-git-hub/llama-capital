from models.market_snapshot import MarketSnapshot
from models.stock import Stock
from providers.base_market_data_provider import BaseMarketDataProvider


class MockMarketDataProvider(BaseMarketDataProvider):
    def fetch(
        self,
        stock: Stock,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            stock=stock,
            market_cap_billion=8.5,
            revenue_growth_percent=22.0,
            debt_to_equity=0.7,
            price=25.0,
            ema_200=20.0,
            above_200_ema=True,
            source="mock",
        )