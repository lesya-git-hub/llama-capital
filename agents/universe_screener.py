from models.screening_result import ScreeningResult
from models.stock import Stock


class UniverseScreener:
    def screen(
        self,
        stock: Stock,
        *,
        market_cap_billion: float,
        revenue_growth_percent: float,
        debt_to_equity: float,
        above_200_ema: bool,
    ) -> ScreeningResult:
        score = 0.0
        reasons: list[str] = []

        if market_cap_billion >= 1:
            score += 25
            reasons.append("Market capitalization is at least $1 billion.")

        if revenue_growth_percent >= 15:
            score += 35
            reasons.append("Revenue growth is at least 15%.")

        if debt_to_equity <= 1:
            score += 20
            reasons.append("Debt-to-equity is within the accepted range.")

        if above_200_ema:
            score += 20
            reasons.append("Price is above the 200-day EMA.")

        return ScreeningResult(
            stock=stock,
            passed=score >= 70,
            score=score,
            reasons=reasons,
        )