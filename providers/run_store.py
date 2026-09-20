from pathlib import Path

from models.llama_capital_run_result import (
    LlamaCapitalRunResult,
)


class RunStore:
    def __init__(
        self,
        directory: str | Path = "runs",
    ) -> None:
        self.directory = Path(directory)

    def save(
        self,
        result: LlamaCapitalRunResult,
    ) -> Path:
        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            self.directory
            / f"{result.run_id}.json"
        )

        path.write_text(
            result.model_dump_json(
                indent=2,
            ),
            encoding="utf-8",
        )

        return path
    def load(
        self,
        run_id: str,
    ) -> LlamaCapitalRunResult:
        path = (
            self.directory
            / f"{run_id}.json"
        )

        return LlamaCapitalRunResult.model_validate_json(
            path.read_text(
                encoding="utf-8",
            )
        )
