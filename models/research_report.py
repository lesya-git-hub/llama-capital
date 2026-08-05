from models.base import LCModel
from models.stock import Stock


class ResearchReport(LCModel):
    stock: Stock
    summary: str
    strengths: list[str]
    risks: list[str]
    recommendation: str
    confidence: float