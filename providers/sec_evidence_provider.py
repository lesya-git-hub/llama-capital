import html
import os
import re

import requests
from dotenv import load_dotenv

from models.evidence import Evidence
from models.stock import Stock
from providers.base_evidence_provider import BaseEvidenceProvider


load_dotenv()


class SECEvidenceProvider(BaseEvidenceProvider):
    TICKERS_URL = (
        "https://www.sec.gov/files/company_tickers.json"
    )

    SUBMISSIONS_URL = (
        "https://data.sec.gov/submissions/CIK{cik}.json"
    )

    ARCHIVES_URL = (
        "https://www.sec.gov/Archives/edgar/data/"
        "{cik_int}/{accession}/{document}"
    )

    def __init__(self) -> None:
        user_agent = os.getenv("SEC_USER_AGENT")

        if not user_agent:
            raise ValueError(
                "SEC_USER_AGENT is missing."
            )

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _fetch_filing_text(
        self,
        url: str,
    ) -> str:
        response = self.session.get(
            url,
            timeout=20,
        )
        response.raise_for_status()

        raw_html = response.text

        text = re.sub(
            r"<script.*?</script>",
            " ",
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        text = re.sub(
            r"<style.*?</style>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        text = re.sub(
            r"<[^>]+>",
            " ",
            text,
        )

        text = html.unescape(text)

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text[:12000]
    
    def _extract_relevant_filing_text(
        self,
        text: str,
        form: str,
    ) -> str:
        if form == "8-K":
            item_match = re.search(
                r"\bItem\s+\d+\.\d+\b",
                text,
                flags=re.IGNORECASE,
            )

            if item_match:
                text = text[item_match.start():]

        # Remove common inline-XBRL / taxonomy noise.
        text = re.sub(
            r"\b(?:xbrli|iso4217|us-gaap|dei|rklb):[A-Za-z0-9_-]+\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text[:8000]

    def _get_cik(
        self,
        ticker: str,
    ) -> str:
        response = self.session.get(
            self.TICKERS_URL,
            timeout=20,
        )
        response.raise_for_status()

        companies = response.json()

        for company in companies.values():
            if company["ticker"].upper() == ticker.upper():
                return str(
                    company["cik_str"]
                ).zfill(10)

        raise ValueError(
            f"CIK not found for ticker {ticker}."
        )

    def fetch(
        self,
        stock: Stock,
    ) -> list[Evidence]:
        cik = self._get_cik(stock.ticker)

        response = self.session.get(
            self.SUBMISSIONS_URL.format(
                cik=cik,
            ),
            timeout=20,
        )
        response.raise_for_status()

        data = response.json()

        recent = data["filings"]["recent"]

        evidence_items: list[Evidence] = []

        useful_forms = {
            "8-K",
            "10-Q",
            "10-K",
            "6-K",
            "20-F",
        }

        for (
            form,
            filing_date,
            accession_number,
            primary_document,
        ) in zip(
            recent["form"],
            recent["filingDate"],
            recent["accessionNumber"],
            recent["primaryDocument"],
        ):
            if form not in useful_forms:
                continue

            accession_clean = accession_number.replace(
                "-",
                "",
            )

            url = self.ARCHIVES_URL.format(
                cik_int=int(cik),
                accession=accession_clean,
                document=primary_document,
            )

            filing_text = self._fetch_filing_text(url)

            filing_text = self._extract_relevant_filing_text(
                filing_text,
                form,
)

            evidence_items.append(
                Evidence(
                    stock=stock,
                    source="SEC",
                    headline=(
                        f"{stock.company} filed "
                        f"{form} on {filing_date}"
                    ),
                    content=filing_text,
                    url=url,
                )
            )

            if len(evidence_items) >= 10:
                break

        return evidence_items