from models.base import LCModel
from models.stock import Stock
from models.evidence import Evidence


class Opportunity(LCModel):
    stock: Stock

    event: str

    importance: int

    evidence: Evidence