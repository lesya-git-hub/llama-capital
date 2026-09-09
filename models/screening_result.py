from models.base import LCModel
from models.stock import Stock


class ScreeningResult(LCModel):
    stock: Stock
    passed: bool
    score: float
    ranking_score: float = 0.0
    reasons: list[str]