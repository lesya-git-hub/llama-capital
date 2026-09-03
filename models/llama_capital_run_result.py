from pydantic import Field

from models.base import LCModel
from models.committee_decision import CommitteeDecision
from models.shortlist_intelligence_result import (
    ShortlistIntelligenceResult,
)
from models.shortlist_research_result import (
    ShortlistResearchResult,
)
from models.universe_discovery_result import (
    UniverseDiscoveryResult,
)
from models.universe_shortlist import UniverseShortlist


class LlamaCapitalRunResult(LCModel):
    universe: UniverseDiscoveryResult
    shortlist: UniverseShortlist
    intelligence: ShortlistIntelligenceResult
    research: ShortlistResearchResult

    committee_decisions: list[
        CommitteeDecision
    ] = Field(
        default_factory=list
    )