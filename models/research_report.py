from models.base import LCModel
from models.stock import Stock
from models.enums import Recommendation


class ResearchReport(LCModel):
    stock: Stock
    summary: str
    strengths: list[str]
    risks: list[str]
    recommendation: Recommendation
    confidence: float