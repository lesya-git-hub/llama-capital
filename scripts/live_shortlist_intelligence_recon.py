from config.universe_v01 import UNIVERSE_V01
from providers.configured_universe_provider import (
    ConfiguredUniverseProvider,
)
from providers.finnhub_market_data_provider import (
    FinnhubMarketDataProvider,
)
from providers.finnhub_universe_provider import (
    FinnhubUniverseProvider,
)
from providers.sec_evidence_provider import (
    SECEvidenceProvider,
)
from sentence_transformers import SentenceTransformer
from tools.evidence_matcher import EvidenceMatcher
from tools.event_clusterer import SemanticEventClusterer
from tools.universe_shortlister import UniverseShortlister
from workflows.intelligence_pipeline import (
    IntelligencePipeline,
)
from workflows.llama_capital_orchestrator import (
    LlamaCapitalOrchestrator,
)
from workflows.shortlist_intelligence_pipeline import (
    ShortlistIntelligencePipeline,
)
from workflows.universe_discovery_pipeline import (
    UniverseDiscoveryPipeline,
)
from tools.source_quality import get_source_type
from providers.run_store import RunStore


def main() -> None:
    universe_provider = ConfiguredUniverseProvider(
        source_provider=FinnhubUniverseProvider(),
        config=UNIVERSE_V01,
    )

    market_data_provider = FinnhubMarketDataProvider()

    universe_discovery_pipeline = (
        UniverseDiscoveryPipeline(
            universe_provider=universe_provider,
            market_data_provider=market_data_provider,
        )
    )

    embedding_model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2"
    )

    clusterer = SemanticEventClusterer(
        model=embedding_model,
        threshold=0.60,
    )

    evidence_matcher = EvidenceMatcher(
        model=embedding_model,
        threshold=0.65,
    )

    intelligence_pipeline = IntelligencePipeline(
        clusterer=clusterer,
        corroboration_provider=SECEvidenceProvider(),
        evidence_matcher=evidence_matcher,
    )

    shortlist_intelligence_pipeline = (
        ShortlistIntelligencePipeline(
            intelligence_pipeline=(
                intelligence_pipeline
            ),
        )
    )

    llama = LlamaCapitalOrchestrator(
        universe_discovery_pipeline=(
            universe_discovery_pipeline
        ),
        shortlist_intelligence_pipeline=(
            shortlist_intelligence_pipeline
        ),
        shortlister=UniverseShortlister(
            max_candidates=5,
        ),
    )

    result = llama.run(
        max_evidence=10,
    )

    run_store = RunStore()
    saved_path = run_store.save(result)

    print()
    print("RUN ARCHIVE")
    print("Run ID:", result.run_id)
    print("Saved:", saved_path)

    print()
    print("=" * 100)
    print("UNIVERSE SCREENING")

    for screening in result.universe.screening_results:
        print(
            screening.stock.ticker,
            "|",
            screening.score,
            "|",
            "PASS" if screening.passed else "FAIL",
        )

    if result.universe.failures:
        print()
        print("Universe failures:")

        for failure in result.universe.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )

    print()
    print("=" * 100)
    print("SHORTLIST")
    print("=" * 100)

    for rank, candidate in enumerate(
        result.shortlist.candidates,
        start=1,
    ):
        print(
            f"#{rank}",
            candidate.stock.ticker,
            "|",
            candidate.stock.company,
            "|",
            candidate.score,
        )

    print()
    print("=" * 100)
    print("INTELLIGENCE")
    print("=" * 100)

    for candidate in result.shortlist.candidates:
        ticker = candidate.stock.ticker

        analyses = (
            result.intelligence
            .analyses_by_ticker.get(
                ticker,
                [],
            )
        )

        print()
        print(
            ticker,
            "|",
            candidate.stock.company,
        )

        if not analyses:
            print("No intelligence events.")
            continue

        for analysis in analyses:
            print(
                "-",
                analysis.cluster.title,
            )
            print(
                "  Type:",
                analysis.event_type.value,
            )
            print(
                "  Opportunity:",
                analysis.opportunity_score,
            )
            print(
                "  Eligible:",
                analysis.eligible_for_research,
            )
            print(
                "  Reason:",
                analysis.eligibility_reason,
            )
            print(
                "  Corroboration:",
                analysis.corroboration_score,
            )

            print(
                "  Evidence:"
            )

            for item in analysis.cluster.evidence_items:
                print(
                    "   - Source:",
                    item.source,
                )
                print(
                    "     Source type:",
                    get_source_type(
                        item.source
                    ).value,
                )
                print(
                    "     Headline:",
                    item.headline,
                )
                print(
                    "     URL:",
                    item.url,
                )

    if result.intelligence.failures:
        print()
        print("Intelligence failures:")

        for failure in result.intelligence.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )

    print()
    print("=" * 100)
    print("RESEARCH")
    print("=" * 100)

    for candidate in result.shortlist.candidates:
        ticker = candidate.stock.ticker

        research = (
            result.research
            .results_by_ticker.get(
                ticker
            )
        )

        print()
        print(
            ticker,
            "|",
            candidate.stock.company,
        )

        if research is None:
            print("No research result.")
            continue

        print(
            "Status:",
            research.status.value,
        )

        print(
            "Reason:",
            research.reason,
        )

        if research.selected_event:
            print(
                "Selected event:",
                research.selected_event,
            )

        report = research.research_report

        if report is None:
            continue

        print(
            "Recommendation:",
            report.recommendation.value,
        )

        print(
            "Confidence:",
            report.confidence,
        )

        print(
            "QA:",
            research.qa_passed,
        )

        print(
            "iQA:",
            research.iqa_passed,
        )

    if result.research.failures:
        print()
        print("Research failures:")

        for failure in result.research.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )

    print()
    print("=" * 100)
    print("COMMITTEE")
    print("=" * 100)

    if not result.committee_decisions:
        print("No committee candidates.")
    else:
        for decision in result.committee_decisions:
            print()
            print(
                decision.stock.ticker,
                "|",
                decision.decision.value,
            )

            print(
                "Allocation:",
                f"{decision.allocation_percent}%",
            )

            print(
                "Confidence:",
                decision.confidence,
            )

            for reason in decision.rationale:
                print(
                    "-",
                    reason,
                )


if __name__ == "__main__":
    main()