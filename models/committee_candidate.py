from models.base import LCModel
from models.research_report import ResearchReport
from models.screening_result import ScreeningResult


class CommitteeCandidate(LCModel):
    screening: ScreeningResult
    research: ResearchReport

    qa_passed: bool
    iqa_passed: bool