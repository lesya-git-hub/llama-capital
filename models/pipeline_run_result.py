from pydantic import Field

from models.base import LCModel
from models.pipeline_status import PipelineStatus
from models.research_report import ResearchReport
from models.stock import Stock


class PipelineRunResult(LCModel):
    status: PipelineStatus

    stock: Stock

    selected_event: str | None = None

    research_report: ResearchReport | None = None

    qa_passed: bool | None = None
    qa_issues: list[str] = Field(
        default_factory=list
    )

    iqa_passed: bool | None = None
    iqa_issues: list[str] = Field(
        default_factory=list
    )

    reason: str | None = None