from models.pipeline_status import PipelineStatus


def test_pipeline_status_values() -> None:
    assert PipelineStatus.NO_ACTION.value == "NO_ACTION"
    assert PipelineStatus.POLICY_BLOCK.value == "POLICY_BLOCK"
    assert (
        PipelineStatus.RESEARCH_COMPLETED.value
        == "RESEARCH_COMPLETED"
    )