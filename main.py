from models.opportunity import Opportunity
from models.stock import Stock
from workflows.opportunity_pipeline import OpportunityPipeline


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