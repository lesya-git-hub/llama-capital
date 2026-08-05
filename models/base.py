from datetime import datetime, UTC

from pydantic import BaseModel, ConfigDict, Field


class LCModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def update(self) -> None:
        self.updated_at = datetime.now(UTC)