from pydantic import Field

from models.base import LCModel
from models.screening_result import ScreeningResult


class UniverseScreeningFailure(LCModel):
    ticker: str
    reason: str


class UniverseDiscoveryResult(LCModel):
    screening_results: list[ScreeningResult] = Field(
        default_factory=list
    )

    failures: list[UniverseScreeningFailure] = Field(
        default_factory=list
    )