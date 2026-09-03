from models.shortlist_intelligence_result import (
    ShortlistIntelligenceResult,
)
from models.shortlist_research_result import (
    ShortlistResearchResult,
)
from models.stock import Stock
from models.universe_discovery_result import (
    UniverseDiscoveryResult,
)
from models.universe_shortlist import (
    UniverseShortlist,
)
from workflows.llama_capital_orchestrator import (
    LlamaCapitalOrchestrator,
)


class FakeUniverseDiscoveryPipeline:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def run(self) -> UniverseDiscoveryResult:
        self.calls.append("universe")

        return UniverseDiscoveryResult()


class FakeShortlister:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def select(
        self,
        screening_results,
    ) -> UniverseShortlist:
        self.calls.append("shortlist")

        return UniverseShortlist()


class FakeIntelligencePipeline:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def run(
        self,
        candidates,
        *,
        max_evidence: int = 10,
    ) -> ShortlistIntelligenceResult:
        self.calls.append("intelligence")

        return ShortlistIntelligenceResult()


class FakeResearchPipeline:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def run(
        self,
        intelligence_result,
    ) -> ShortlistResearchResult:
        self.calls.append("research")

        return ShortlistResearchResult()


class FakeCandidateBuilder:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def build(
        self,
        screening_results,
        research_results,
    ) -> list:
        self.calls.append("candidate_builder")

        return []


class FakeCommitteePipeline:
    def __init__(
        self,
        calls: list[str],
    ) -> None:
        self.calls = calls

    def run(
        self,
        candidates,
    ) -> list:
        self.calls.append("committee")

        return []


def test_llama_capital_orchestrates_stages_in_order() -> None:
    calls: list[str] = []

    orchestrator = LlamaCapitalOrchestrator(
        universe_discovery_pipeline=(
            FakeUniverseDiscoveryPipeline(
                calls
            )
        ),
        shortlist_intelligence_pipeline=(
            FakeIntelligencePipeline(
                calls
            )
        ),
        shortlister=FakeShortlister(
            calls
        ),
        shortlist_research_pipeline=(
            FakeResearchPipeline(
                calls
            )
        ),
        candidate_builder=(
            FakeCandidateBuilder(
                calls
            )
        ),
        committee_pipeline=(
            FakeCommitteePipeline(
                calls
            )
        ),
    )

    result = orchestrator.run(
        max_evidence=5
    )

    assert calls == [
        "universe",
        "shortlist",
        "intelligence",
        "research",
        "candidate_builder",
        "committee",
    ]

    assert result.universe.screening_results == []
    assert result.shortlist.candidates == []
    assert (
        result.intelligence.analyses_by_ticker
        == {}
    )
    assert (
        result.research.results_by_ticker
        == {}
    )
    assert result.committee_decisions == []