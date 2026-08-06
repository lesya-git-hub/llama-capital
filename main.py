from models.opportunity import Opportunity
from models.stock import Stock
from workflows.opportunity_pipeline import OpportunityPipeline
from agents.committee_agent import CommitteeAgent
from workflows.universe_pipeline import UniversePipeline

stock = Stock(
    ticker="RKLB",
    company="Rocket Lab",
    sector="Industrials",
    industry="Aerospace",
    exchange="NASDAQ",
)

opportunity = Opportunity(
    stock=stock,
    event="Won new government contract",
    importance=8,
    source="Reuters",
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

report, passed, issues = pipeline.run(opportunity)

print()
print("Pipeline Result")
print("Passed:", passed)
print("Ticker:", report.stock.ticker)
print("Recommendation:", report.recommendation)
print("Confidence:", report.confidence)
print("Summary:", report.summary)

print("Strengths:")
for strength in report.strengths:
    print("-", strength)

print("Risks:")
for risk in report.risks:
    print("-", risk)

for issue in issues:
    print("QA issue:", issue)


committee = CommitteeAgent()

decision = committee.decide(
    screening=screening_result,
    research=report,
)

print()
print("Committee Decision")
print("Decision:", decision.decision)
print("Allocation:", f"{decision.allocation_percent}%")
print("Confidence:", decision.confidence)

print("Rationale:")
for reason in decision.rationale:
    print("-", reason)