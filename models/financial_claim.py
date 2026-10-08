from enum import StrEnum
from pydantic import model_validator
from models.base import LCModel


class FinancialPeriod(StrEnum):
    QUARTER = "quarter"
    FULL_YEAR = "full_year"
    UNKNOWN = "unknown"


class FinancialClaimStatus(StrEnum):
    ACTUAL = "actual"
    GUIDANCE = "guidance"
    UNKNOWN = "unknown"


class FinancialClaim(LCModel):
    metric: str
    value: float
    unit: str
    period: FinancialPeriod = FinancialPeriod.UNKNOWN
    year: int | None = None
    quarter: int | None = None
    status: FinancialClaimStatus = FinancialClaimStatus.UNKNOWN
    @model_validator(mode="after")
    def validate_period_scope(self) -> "FinancialClaim":
        if (
            self.period == FinancialPeriod.QUARTER
            and self.quarter is None
        ):
            raise ValueError(
                "quarter is required for quarterly claims"
            )

        return self