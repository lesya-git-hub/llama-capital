from models.base import LCModel
from models.stock import Stock


class Opportunity(LCModel):
    stock: Stock

    event: str

    importance: int

    source: str