from models.base import LCModel
from models.stock import Stock


class ScreeningResult(LCModel):
    stock: Stock
    passed: bool
    score: float
    reasons: list[str]