from models.base import LCModel
from models.evidence import Evidence
from models.stock import Stock


class EventCluster(LCModel):
    stock: Stock
    title: str
    evidence_items: list[Evidence]