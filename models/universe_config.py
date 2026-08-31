from dataclasses import dataclass, field


@dataclass(frozen=True)
class UniverseConfig:
    max_candidates: int = 50

    allowed_tickers: set[str] = field(
        default_factory=set,
    )