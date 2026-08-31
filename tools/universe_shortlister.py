from models.screening_result import ScreeningResult
from models.universe_shortlist import UniverseShortlist


class UniverseShortlister:
    def __init__(
        self,
        max_candidates: int = 10,
    ) -> None:
        if max_candidates <= 0:
            raise ValueError(
                "max_candidates must be greater than zero."
            )

        self.max_candidates = max_candidates

    def select(
        self,
        results: list[ScreeningResult],
    ) -> UniverseShortlist:
        eligible = [
            result
            for result in results
            if result.passed
        ]

        ranked = sorted(
            eligible,
            key=lambda result: result.score,
            reverse=True,
        )

        return UniverseShortlist(
            candidates=ranked[
                :self.max_candidates
            ]
        )