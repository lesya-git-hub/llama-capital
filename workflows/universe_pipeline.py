from agents.universe_screener import UniverseScreener
from models.screening_result import ScreeningResult
from models.stock import Stock


class UniversePipeline:
    def __init__(self) -> None:
        self.screener = UniverseScreener()

    def run(
        self,
        stock: Stock,
        *,
        market_cap_billion: float,
        revenue_growth_percent: float,
        debt_to_equity: float,
        above_200_ema: bool,
    ) -> ScreeningResult:
        return self.screener.screen(
            stock,
            market_cap_billion=market_cap_billion,
            revenue_growth_percent=revenue_growth_percent,
            debt_to_equity=debt_to_equity,
            above_200_ema=above_200_ema,
        )