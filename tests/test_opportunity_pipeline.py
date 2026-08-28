import pytest

from models.evidence import Evidence
from models.event_analysis import (
    ArticleKind,
    ImpactDirection,
)
from models.opportunity import Opportunity
from models.stock import Stock
from workflows.opportunity_pipeline import OpportunityPipeline
from exceptions.opportunity_exceptions import IneligibleOpportunityError

def make_opportunity(
    eligible_for_research: bool,
    eligibility_reason: str,
) -> Opportunity:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    evidence = Evidence(
        stock=stock,
        source="Reuters",
        headline="Rocket Lab wins government contract",
        content="Test evidence.",
        url="https://example.com",
    )

    return Opportunity(
        stock=stock,
        event=evidence.headline,
        importance=8,
        evidence=evidence,
        opportunity_score=80.0,
        impact_direction=ImpactDirection.POSITIVE,
        impact_score=6.0,
        materiality_score=8.0,
        source_quality_score=9.5,
        corroboration_score=6.0,
        strategic_relevance_score=8.0,
        article_kind=ArticleKind.CORPORATE_EVENT,
        is_primary_event=True,
        eligible_for_research=eligible_for_research,
        eligibility_reason=eligibility_reason,
    )


def test_ineligible_opportunity_is_blocked() -> None:
    pipeline = OpportunityPipeline()

    opportunity = make_opportunity(
        eligible_for_research=False,
        eligibility_reason="valuation commentary veto",
    )

    with pytest.raises(
        IneligibleOpportunityError,
        match="Ineligible opportunity reached research pipeline",
    ):
        pipeline.run(opportunity)


def test_eligible_opportunity_reaches_research() -> None:
    pipeline = OpportunityPipeline()

    opportunity = make_opportunity(
        eligible_for_research=True,
        eligibility_reason="eligible for research",
    )

    report, qa_passed, _, iqa_passed, _ = pipeline.run(
        opportunity
    )

    assert report.stock.ticker == "RKLB"
    assert qa_passed is True
    assert iqa_passed is True