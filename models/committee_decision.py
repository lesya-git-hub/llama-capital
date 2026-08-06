from models.base import LCModel
from models.stock import Stock
from models.enums import CommitteeDecisionType


class CommitteeDecision(LCModel):
    stock: Stock

    decision: CommitteeDecisionType

    allocation_percent: float

    confidence: float

    rationale: list[str]