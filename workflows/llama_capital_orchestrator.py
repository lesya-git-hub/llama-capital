from models.llama_capital_run_result import (
    LlamaCapitalRunResult,
)
from tools.committee_candidate_builder import (
    CommitteeCandidateBuilder,
)
from tools.universe_shortlister import (
    UniverseShortlister,
)
from workflows.shortlist_committee_pipeline import (
    ShortlistCommitteePipeline,
)
from workflows.shortlist_intelligence_pipeline import (
    ShortlistIntelligencePipeline,
)
from workflows.shortlist_research_pipeline import (
    ShortlistResearchPipeline,
)
from workflows.universe_discovery_pipeline import (
    UniverseDiscoveryPipeline,
)


class LlamaCapitalOrchestrator:
    def __init__(
        self,
        universe_discovery_pipeline: UniverseDiscoveryPipeline,
        shortlist_intelligence_pipeline: ShortlistIntelligencePipeline,
        *,
        shortlister: UniverseShortlister | None = None,
        shortlist_research_pipeline: ShortlistResearchPipeline | None = None,
        candidate_builder: CommitteeCandidateBuilder | None = None,
        committee_pipeline: ShortlistCommitteePipeline | None = None,
    ) -> None:
        self.universe_discovery_pipeline = (
            universe_discovery_pipeline
        )

        self.shortlist_intelligence_pipeline = (
            shortlist_intelligence_pipeline
        )

        self.shortlister = (
            shortlister
            or UniverseShortlister(
                max_candidates=10,
            )
        )

        self.shortlist_research_pipeline = (
            shortlist_research_pipeline
            or ShortlistResearchPipeline()
        )

        self.candidate_builder = (
            candidate_builder
            or CommitteeCandidateBuilder()
        )

        self.committee_pipeline = (
            committee_pipeline
            or ShortlistCommitteePipeline()
        )

    def run(
        self,
        *,
        max_evidence: int = 10,
    ) -> LlamaCapitalRunResult:
        universe_result = (
            self.universe_discovery_pipeline.run()
        )

        shortlist = self.shortlister.select(
            universe_result.screening_results
        )

        intelligence_result = (
            self.shortlist_intelligence_pipeline.run(
                shortlist.candidates,
                max_evidence=max_evidence,
            )
        )

        research_result = (
            self.shortlist_research_pipeline.run(
                intelligence_result
            )
        )

        committee_candidates = (
            self.candidate_builder.build(
                universe_result.screening_results,
                research_result,
            )
        )

        committee_decisions = (
            self.committee_pipeline.run(
                committee_candidates
            )
        )

        return LlamaCapitalRunResult(
            universe=universe_result,
            shortlist=shortlist,
            intelligence=intelligence_result,
            research=research_result,
            committee_decisions=committee_decisions,
        )