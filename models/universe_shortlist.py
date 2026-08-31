from pydantic import Field

from models.base import LCModel
from models.screening_result import ScreeningResult


class UniverseShortlist(LCModel):
    candidates: list[ScreeningResult] = Field(
        default_factory=list
    )