from pydantic import Field

from models.base import LCModel
from models.event_analysis import EventAnalysis


class IntelligenceFailure(LCModel):
    ticker: str
    reason: str


class ShortlistIntelligenceResult(LCModel):
    analyses_by_ticker: dict[
        str,
        list[EventAnalysis],
    ] = Field(
        default_factory=dict
    )

    failures: list[IntelligenceFailure] = Field(
        default_factory=list
    )