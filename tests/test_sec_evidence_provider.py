from providers.sec_evidence_provider import (
    SECEvidenceProvider,
)
from models.stock import Stock

def test_finds_exhibit_99_1_document() -> None:
    items = [
        {
            "name": "pltr-20260803.htm",
            "type": "text.gif",
        },
        {
            "name": "a2026q2ex991pressrelease.htm",
            "type": "text.gif",
        },
        {
            "name": "FilingSummary.xml",
            "type": "text.gif",
        },
    ]

    result = (
        SECEvidenceProvider.find_exhibit_99_1(
            items
        )
    )

    assert result == (
        "a2026q2ex991pressrelease.htm"
    )
def test_get_filing_directory(
    monkeypatch,
) -> None:
    provider = SECEvidenceProvider.__new__(
        SECEvidenceProvider
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "directory": {
                    "item": [
                        {
                            "name": (
                                "a2026q2ex991pressrelease.htm"
                            )
                        }
                    ]
                }
            }

    class FakeSession:
        def get(
            self,
            url: str,
            timeout: int,
        ) -> FakeResponse:
            assert (
                "000132165526000039/index.json"
                in url
            )
            assert timeout == 20
            return FakeResponse()

    provider.session = FakeSession()

    items = provider._get_filing_directory(
        cik="0001321655",
        accession_number="0001321655-26-000039",
    )

    assert items == [
        {
            "name": (
                "a2026q2ex991pressrelease.htm"
            )
        }
    ]
def test_fetches_exhibit_99_1(
    monkeypatch,
) -> None:
    provider = SECEvidenceProvider.__new__(
        SECEvidenceProvider
    )

    monkeypatch.setattr(
        provider,
        "_get_filing_directory",
        lambda cik, accession_number: [
            {
                "name": (
                    "a2026q2ex991pressrelease.htm"
                )
            }
        ],
    )

    monkeypatch.setattr(
        provider,
        "_fetch_filing_text",
        lambda url: (
            "Palantir Reports Q2 2026. "
            "U.S. commercial revenue grew "
            "149% year-over-year."
        ),
    )

    evidence = provider._fetch_exhibit_99_1(
        stock=Stock(
            ticker="PLTR",
            company="Palantir Technologies",
            sector="Technology",
            industry="Software",
            exchange="NASDAQ",
        ),
        cik="0001321655",
        accession_number="0001321655-26-000039",
        filing_date="2026-08-03",
    )

    assert evidence is not None
    assert evidence.source == "SEC"
    assert "Exhibit 99.1" in evidence.headline
    assert "149%" in evidence.content
    assert (
        "a2026q2ex991pressrelease.htm"
        in evidence.url
    )