import os
from datetime import datetime, timedelta

import finnhub
from dotenv import load_dotenv

from models.evidence import Evidence
from models.stock import Stock
from providers.base_evidence_provider import BaseEvidenceProvider


class FinnhubEvidenceProvider(BaseEvidenceProvider):
    def __init__(self) -> None:
        load_dotenv()

        api_key = os.getenv("FINNHUB_API_KEY")

        if not api_key:
            raise ValueError("FINNHUB_API_KEY is missing.")

        self.client = finnhub.Client(api_key=api_key)

    def fetch(self, stock: Stock) -> list[Evidence]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=7)

        news = self.client.company_news(
            stock.ticker,
            _from=start_date.isoformat(),
            to=end_date.isoformat(),
        )

        evidence: list[Evidence] = []

        for article in news:
            evidence.append(
                Evidence(
                    stock=stock,
                    source=article.get("source", "Unknown"),
                    headline=article.get("headline", ""),
                    content=article.get("summary", ""),
                    url=article.get("url", ""),
                )
            )

        return evidence