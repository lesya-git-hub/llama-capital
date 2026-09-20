from pathlib import Path

from models.llama_capital_run_result import (
    LlamaCapitalRunResult,
)
from providers.run_store import RunStore


def test_run_store_saves_run_as_json(
    tmp_path: Path,
) -> None:
    result = LlamaCapitalRunResult.model_construct(
        run_id="test-run-123",
    )

    store = RunStore(tmp_path)

    saved_path = store.save(result)

    assert saved_path.exists()
    assert saved_path.name == "test-run-123.json"

    saved_content = saved_path.read_text(
        encoding="utf-8",
    )

    assert '"run_id": "test-run-123"' in saved_content

def test_run_store_loads_saved_run(
    tmp_path: Path,
) -> None:
    from models.shortlist_intelligence_result import (
        ShortlistIntelligenceResult,
    )
    from models.shortlist_research_result import (
        ShortlistResearchResult,
    )
    from models.universe_discovery_result import (
        UniverseDiscoveryResult,
    )
    from models.universe_shortlist import (
        UniverseShortlist,
    )

    result = LlamaCapitalRunResult(
        run_id="test-run-456",
        universe=UniverseDiscoveryResult(),
        shortlist=UniverseShortlist(),
        intelligence=ShortlistIntelligenceResult(),
        research=ShortlistResearchResult(),
    )

    store = RunStore(tmp_path)
    store.save(result)

    loaded = store.load("test-run-456")

    assert loaded.run_id == result.run_id
    assert loaded == result