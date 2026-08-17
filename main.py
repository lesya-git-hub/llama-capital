from models.opportunity import Opportunity
from models.stock import Stock
from workflows.opportunity_pipeline import OpportunityPipeline
from agents.committee_agent import CommitteeAgent
from workflows.universe_pipeline import UniversePipeline
from providers.mock_evidence_provider import MockEvidenceProvider

stock = Stock(
    ticker="RKLB",
    company="Rocket Lab",
    sector="Industrials",
    industry="Aerospace",
    exchange="NASDAQ",
)
evidence_provider = MockEvidenceProvider()
evidence_list = evidence_provider.fetch(stock)

evidence = evidence_list[0]

opportunity = Opportunity(
    stock=stock,
    evidence=evidence,
    event=evidence.headline,
    importance=8,
)

universe_pipeline = UniversePipeline()

screening_result = universe_pipeline.run(
    stock,
    market_cap_billion=8.5,
    revenue_growth_percent=22.0,
    debt_to_equity=0.7,
    above_200_ema=True,
)

print()
print("Universe Screening Result")
print("Passed:", screening_result.passed)
print("Score:", screening_result.score)

for reason in screening_result.reasons:
    print("-", reason)

pipeline = OpportunityPipeline()

report, qa_passed, qa_issues, iqa_passed, iqa_issues = pipeline.run(
    opportunity
)

print()
print("Pipeline Result")
print("QA Passed:", qa_passed)
print("iQA Passed:", iqa_passed)

print("Ticker:", report.stock.ticker)
print("Recommendation:", report.recommendation.value)
print("Confidence:", report.confidence)
print("Summary:", report.summary)

print("Strengths:")
for strength in report.strengths:
    print("-", strength)

print("Risks:")
for risk in report.risks:
    print("-", risk)

for issue in qa_issues:
    print("QA issue:", issue)

for issue in iqa_issues:
    print("iQA issue:", issue)
committee = CommitteeAgent()

decision = committee.decide(
    screening=screening_result,
    research=report,
    qa_passed=qa_passed,
    iqa_passed=iqa_passed,
)

print()
print("Committee Decision")
print("Decision:", decision.decision.value)
print("Allocation:", f"{decision.allocation_percent}%")
print("Confidence:", decision.confidence)

print("Rationale:")
for reason in decision.rationale:
    print("-", reason)