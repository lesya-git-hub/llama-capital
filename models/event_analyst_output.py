from pydantic import BaseModel, Field

from models.event_analysis import EventType, ImpactDirection


class EventAnalystOutput(BaseModel):
    event_type: EventType

    impact_direction: ImpactDirection

    impact_score: float = Field(
        ge=-10.0,
        le=10.0,
    )

    materiality_score: float = Field(
        ge=0.0,
        le=10.0,
    )

    summary: str

    bull_case: list[str]

    bear_case: list[str]

    uncertainties: list[str]

    rationale: str