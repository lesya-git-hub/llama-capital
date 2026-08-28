from agents.universe_screener import UniverseScreener
from models.market_snapshot import MarketSnapshot
from models.screening_result import ScreeningResult


class UniversePipeline:
    def __init__(self) -> None:
        self.screener = UniverseScreener()

    def run(
        self,
        snapshot: MarketSnapshot,
    ) -> ScreeningResult:
        return self.screener.screen(
            snapshot.stock,
            market_cap_billion=snapshot.market_cap_billion,
            revenue_growth_percent=snapshot.revenue_growth_percent,
            debt_to_equity=snapshot.debt_to_equity,
            above_200_ema=snapshot.above_200_ema,
        )