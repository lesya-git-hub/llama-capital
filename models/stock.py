from pydantic import BaseModel, Field
from models.base import LCModel


class Stock(LCModel):
    ticker: str = Field(..., description="Stock ticker")
    company: str = Field(..., description="Company name")
    sector: str = Field(..., description="Market sector")
    industry: str = Field(..., description="Industry")
    exchange: str = Field(..., description="Exchange")