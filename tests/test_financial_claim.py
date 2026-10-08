import pytest
from pydantic import ValidationError

from models.financial_claim import (
    FinancialClaim,
    FinancialClaimStatus,
    FinancialPeriod,
)


def test_financial_claim_preserves_scope() -> None:
    claim = FinancialClaim(
        metric="commercial_revenue",
        value=507.0,
        unit="million",
        period=FinancialPeriod.QUARTER,
        year=2025,
        quarter=4,
        status=FinancialClaimStatus.ACTUAL,
    )

    assert claim.metric == "commercial_revenue"
    assert claim.value == 507.0
    assert claim.period == FinancialPeriod.QUARTER
    assert claim.year == 2025
    assert claim.quarter == 4
    assert claim.status == FinancialClaimStatus.ACTUAL

def test_quarterly_financial_claim_requires_quarter() -> None:
    with pytest.raises(ValidationError):
        FinancialClaim(
            metric="commercial_revenue",
            value=507.0,
            unit="million",
            period=FinancialPeriod.QUARTER,
            year=2025,
            status=FinancialClaimStatus.ACTUAL,
        )