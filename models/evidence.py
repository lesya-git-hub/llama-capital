from models.base import LCModel
from models.stock import Stock


class Evidence(LCModel):
    stock: Stock
    source: str
    headline: str
    content: str
    url: str