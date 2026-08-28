from datetime import UTC, datetime

from pydantic import Field

from models.base import LCModel
from models.stock import Stock


class MarketSnapshot(LCModel):
    stock: Stock

    market_cap_billion: float
    revenue_growth_percent: float
    debt_to_equity: float

    price: float | None = None
    ema_200: float | None = None
    above_200_ema: bool

    source: str

    as_of: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )