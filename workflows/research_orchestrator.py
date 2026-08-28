from exceptions.opportunity_exceptions import (
    IneligibleOpportunityError,
)
from models.opportunity import Opportunity
from models.pipeline_run_result import PipelineRunResult
from models.pipeline_status import PipelineStatus
from models.stock import Stock
from tools.event_eligibility import select_top_eligible_event
from workflows.opportunity_pipeline import OpportunityPipeline


class ResearchOrchestrator:
    def __init__(
        self,
        opportunity_pipeline=None,
    ) -> None:
        self.opportunity_pipeline = (
            opportunity_pipeline
            or OpportunityPipeline()
        )

    def run(
        self,
        stock: Stock,
        ranked_opportunities,
    ) -> PipelineRunResult:
        top_analysis = select_top_eligible_event(
            ranked_opportunities,
        )

        if top_analysis is None:
            return PipelineRunResult(
                status=PipelineStatus.NO_ACTION,
                stock=stock,
                reason=(
                    "No eligible primary corporate "
                    "event found."
                ),
            )

        top_evidence = (
            top_analysis.cluster.evidence_items[0]
        )

        opportunity = Opportunity(
            stock=stock,
            evidence=top_evidence,
            event=top_analysis.cluster.title,
            importance=round(
                top_analysis.importance_score
            ),
            opportunity_score=(
                top_analysis.opportunity_score
            ),
            impact_direction=(
                top_analysis.impact_direction
            ),
            impact_score=top_analysis.impact_score,
            materiality_score=(
                top_analysis.importance_score
            ),
            source_quality_score=(
                top_analysis.source_quality_score
            ),
            corroboration_score=(
                top_analysis.corroboration_score
            ),
            strategic_relevance_score=(
                top_analysis.strategic_relevance_score
            ),
            article_kind=top_analysis.article_kind,
            is_primary_event=(
                top_analysis.is_primary_event
            ),
            eligible_for_research=(
                top_analysis.eligible_for_research
            ),
            eligibility_reason=(
                top_analysis.eligibility_reason
            ),
        )

        try:
            (
                report,
                qa_passed,
                qa_issues,
                iqa_passed,
                iqa_issues,
            ) = self.opportunity_pipeline.run(
                opportunity
            )

        except IneligibleOpportunityError as error:
            return PipelineRunResult(
                status=PipelineStatus.POLICY_BLOCK,
                stock=stock,
                selected_event=opportunity.event,
                reason=str(error),
            )

        return PipelineRunResult(
            status=PipelineStatus.RESEARCH_COMPLETED,
            stock=stock,
            selected_event=opportunity.event,
            research_report=report,
            qa_passed=qa_passed,
            qa_issues=qa_issues,
            iqa_passed=iqa_passed,
            iqa_issues=iqa_issues,
            reason="Research pipeline completed.",
        )