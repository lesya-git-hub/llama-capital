from models.stock import Stock
from providers.mock_evidence_provider import MockEvidenceProvider


def test_mock_provider_returns_evidence() -> None:
    stock = Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )

    provider = MockEvidenceProvider()
    evidence_list = provider.fetch(stock)

    assert len(evidence_list) == 1

    evidence = evidence_list[0]

    assert evidence.stock.ticker == "RKLB"
    assert evidence.source == "Reuters"
    assert evidence.headline
    assert evidence.content
    assert evidence.url