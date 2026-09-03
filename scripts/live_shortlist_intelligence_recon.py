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
from workflows.shortlist_intelligence_pipeline import (
    ShortlistIntelligencePipeline,
)
from workflows.universe_discovery_pipeline import (
    UniverseDiscoveryPipeline,
)
from workflows.shortlist_research_pipeline import (
    ShortlistResearchPipeline,
)


def main() -> None:
    universe_provider = ConfiguredUniverseProvider(
        source_provider=FinnhubUniverseProvider(),
        config=UNIVERSE_V01,
    )

    market_data_provider = (
        FinnhubMarketDataProvider()
    )

    discovery_pipeline = UniverseDiscoveryPipeline(
        universe_provider=universe_provider,
        market_data_provider=market_data_provider,
    )

    discovery_result = discovery_pipeline.run()

    shortlister = UniverseShortlister(
        max_candidates=3,
    )

    shortlist = shortlister.select(
        discovery_result.screening_results
    )
    if discovery_result.failures:
        print()
        print("=" * 100)
        print("UNIVERSE SCREENING FAILURES")
        print("=" * 100)

        for failure in discovery_result.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )
    print()
    print("=" * 100)
    print("LIVE INTELLIGENCE SHORTLIST")
    print("=" * 100)

    for rank, candidate in enumerate(
        shortlist.candidates,
        start=1,
    ):
        print(
            f"#{rank} "
            f"{candidate.stock.ticker} | "
            f"{candidate.stock.company} | "
            f"screening score: {candidate.score}"
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

    shortlist_pipeline = (
        ShortlistIntelligencePipeline(
            intelligence_pipeline=(
                intelligence_pipeline
            ),
        )
    )

    result = shortlist_pipeline.run(
        shortlist.candidates,
        max_evidence=10,
    )

    print()
    print("=" * 100)
    print("INTELLIGENCE RESULTS")
    print("=" * 100)

    for candidate in shortlist.candidates:
        ticker = candidate.stock.ticker

        analyses = (
            result.analyses_by_ticker.get(
                ticker,
                [],
            )
        )

        print()
        print("-" * 100)
        print(
            ticker,
            "|",
            candidate.stock.company,
        )
        print("-" * 100)

        if not analyses:
            print("No intelligence events found.")
            continue

        for rank, analysis in enumerate(
            analyses,
            start=1,
        ):
            print()
            print(f"Event #{rank}")
            print(
                "Title:",
                analysis.cluster.title,
            )
            print(
                "Type:",
                analysis.event_type.value,
            )
            print(
                "Article kind:",
                analysis.article_kind.value,
            )
            print(
                "Primary:",
                analysis.is_primary_event,
            )
            print(
                "Impact:",
                analysis.impact_direction.value,
            )
            print(
                "Impact score:",
                analysis.impact_score,
            )
            print(
                "Opportunity score:",
                analysis.opportunity_score,
            )
            print(
                "Eligible:",
                analysis.eligible_for_research,
            )
            print(
                "Eligibility reason:",
                analysis.eligibility_reason,
            )

            sources = [
                item.source
                for item
                in analysis.cluster.evidence_items
            ]

            print(
                "Sources:",
                sources,
            )

    print()
    print("=" * 100)
    print("INTELLIGENCE FAILURES")
    print("=" * 100)

    if not result.failures:
        print("None")
    else:
        for failure in result.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )
    research_pipeline = (
        ShortlistResearchPipeline()
    )

    research_result = research_pipeline.run(
        result
    )

    print()
    print("=" * 100)
    print("RESEARCH RESULTS")
    print("=" * 100)

    for candidate in shortlist.candidates:
        ticker = candidate.stock.ticker

        pipeline_result = (
            research_result.results_by_ticker.get(
                ticker
            )
        )

        print()
        print("-" * 100)
        print(
            ticker,
            "|",
            candidate.stock.company,
        )
        print("-" * 100)

        if pipeline_result is None:
            print(
                "No research result."
            )
            continue

        print(
            "Status:",
            pipeline_result.status.value,
        )

        print(
            "Reason:",
            pipeline_result.reason,
        )

        if pipeline_result.selected_event:
            print(
                "Selected event:",
                pipeline_result.selected_event,
            )

        report = (
            pipeline_result.research_report
        )

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
            "Summary:",
            report.summary,
        )

        print(
            "QA Passed:",
            pipeline_result.qa_passed,
        )

        print(
            "iQA Passed:",
            pipeline_result.iqa_passed,
        )

        if pipeline_result.qa_issues:
            print("QA Issues:")

            for issue in pipeline_result.qa_issues:
                print(
                    "-",
                    issue,
                )

        if pipeline_result.iqa_issues:
            print("iQA Issues:")

            for issue in pipeline_result.iqa_issues:
                print(
                    "-",
                    issue,
                )

        print("Strengths:")

        for strength in report.strengths:
            print(
                "-",
                strength,
            )

        print("Risks:")

        for risk in report.risks:
            print(
                "-",
                risk,
            )

    print()
    print("=" * 100)
    print("RESEARCH FAILURES")
    print("=" * 100)

    if not research_result.failures:
        print("None")
    else:
        for failure in research_result.failures:
            print(
                failure.ticker,
                "|",
                failure.reason,
            )


if __name__ == "__main__":
    main()