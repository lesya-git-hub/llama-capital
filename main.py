from agents.committee_agent import CommitteeAgent
from models.pipeline_status import PipelineStatus
from models.stock import Stock
from providers.sec_evidence_provider import SECEvidenceProvider
from sentence_transformers import SentenceTransformer
from tools.evidence_matcher import EvidenceMatcher
from tools.event_clusterer import SemanticEventClusterer
from workflows.intelligence_pipeline import IntelligencePipeline
from workflows.research_orchestrator import ResearchOrchestrator
from workflows.universe_pipeline import UniversePipeline
from providers.finnhub_market_data_provider import (
    FinnhubMarketDataProvider,
)

stock = Stock(
    ticker="RKLB",
    company="Rocket Lab",
    sector="Industrials",
    industry="Aerospace",
    exchange="NASDAQ",
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

ranked_opportunities = intelligence_pipeline.run(
    stock,
    max_evidence=10,
)


print()
print("=" * 100)
print("LIVE INTELLIGENCE")
print("=" * 100)

for rank, analysis in enumerate(
    ranked_opportunities,
    start=1,
):
    print()
    print(f"#{rank}")
    print("Event:", analysis.cluster.title)
    print("Type:", analysis.event_type.value)
    print("Article kind:", analysis.article_kind.value)
    print("Primary event:", analysis.is_primary_event)
    print("Impact:", analysis.impact_direction.value)
    print("Impact score:", analysis.impact_score)
    print(
        "Opportunity score:",
        analysis.opportunity_score,
    )

    print(
        "Sources:",
        [
            item.source
            for item in analysis.cluster.evidence_items
        ],
    )

    print(
        "Corroboration:",
        analysis.corroboration_score,
    )

    print(
        "Source quality:",
        analysis.source_quality_score,
    )

    official_evidence = [
        item
        for item in analysis.cluster.evidence_items
        if item.source.upper() == "SEC"
    ]

    print(
        "Official corroboration:",
        "YES" if official_evidence else "NO",
    )

    for item in official_evidence:
        print(
            "Matched official filing:",
            item.headline,
        )

    print(
        "Eligible for research:",
        (
            "YES"
            if analysis.eligible_for_research
            else "NO"
        ),
    )

    print(
        "Eligibility reason:",
        analysis.eligibility_reason,
    )

market_data_provider = FinnhubMarketDataProvider()

snapshot = market_data_provider.fetch(
    stock
)

universe_pipeline = UniversePipeline()

screening_result = universe_pipeline.run(
    snapshot
)

print()
print("=" * 100)
print("MARKET SNAPSHOT")
print("=" * 100)

print(
    "Market cap:",
    snapshot.market_cap_billion,
    "B",
)
print(
    "Revenue growth:",
    snapshot.revenue_growth_percent,
    "%",
)
print(
    "Debt / equity:",
    snapshot.debt_to_equity,
)
print(
    "Price:",
    snapshot.price,
)
print(
    "EMA 200:",
    snapshot.ema_200,
)
print(
    "Above EMA 200:",
    snapshot.above_200_ema,
)
print(
    "Source:",
    snapshot.source,
)

print()
print("=" * 100)
print("UNIVERSE SCREENING")
print("=" * 100)

print("Passed:", screening_result.passed)
print("Score:", screening_result.score)

for reason in screening_result.reasons:
    print("-", reason)
research_orchestrator = ResearchOrchestrator()

research_result = research_orchestrator.run(
    stock=stock,
    ranked_opportunities=ranked_opportunities,
)


if research_result.status != PipelineStatus.RESEARCH_COMPLETED:
    print()
    print("=" * 100)
    print("RESEARCH GATE")
    print("=" * 100)
    print("Status:", research_result.status.value)
    print("Reason:", research_result.reason)
    print("Decision: NO ACTION")

else:
    report = research_result.research_report

    if report is None:
        raise RuntimeError(
            "Research completed without a research report."
        )

    print()
    print("Pipeline Result")
    print(
        "Status:",
        research_result.status.value,
    )
    print(
        "QA Passed:",
        research_result.qa_passed,
    )
    print(
        "iQA Passed:",
        research_result.iqa_passed,
    )

    print("Ticker:", report.stock.ticker)
    print(
        "Recommendation:",
        report.recommendation.value,
    )
    print("Confidence:", report.confidence)
    print("Summary:", report.summary)

    print("Strengths:")
    for strength in report.strengths:
        print("-", strength)

    print("Risks:")
    for risk in report.risks:
        print("-", risk)

    for issue in research_result.qa_issues:
        print("QA issue:", issue)

    for issue in research_result.iqa_issues:
        print("iQA issue:", issue)

    committee = CommitteeAgent()

    decision = committee.decide(
        screening=screening_result,
        research=report,
        qa_passed=bool(
            research_result.qa_passed
        ),
        iqa_passed=bool(
            research_result.iqa_passed
        ),
    )

    print()
    print("Committee Decision")
    print("Decision:", decision.decision.value)
    print(
        "Allocation:",
        f"{decision.allocation_percent}%",
    )
    print("Confidence:", decision.confidence)

    print("Rationale:")
    for reason in decision.rationale:
        print("-", reason)