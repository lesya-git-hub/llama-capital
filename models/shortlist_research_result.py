from pydantic import Field

from models.base import LCModel
from models.pipeline_run_result import PipelineRunResult


class ResearchFailure(LCModel):
    ticker: str
    reason: str


class ShortlistResearchResult(LCModel):
    results_by_ticker: dict[
        str,
        PipelineRunResult,
    ] = Field(
        default_factory=dict
    )

    failures: list[ResearchFailure] = Field(
        default_factory=list
    )