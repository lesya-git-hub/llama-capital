from models.pipeline_run_result import PipelineRunResult
from models.pipeline_status import PipelineStatus
from models.stock import Stock


def test_pipeline_run_result_supports_no_action() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    result = PipelineRunResult(
        status=PipelineStatus.NO_ACTION,
        stock=stock,
        reason="No eligible event found.",
    )

    assert result.status == PipelineStatus.NO_ACTION
    assert result.stock.ticker == "RKLB"
    assert result.research_report is None
    assert result.qa_issues == []
    assert result.iqa_issues == []