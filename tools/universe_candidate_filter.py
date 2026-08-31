from models.stock import Stock


class UniverseCandidateFilter:
    def __init__(
        self,
        max_candidates: int = 100,
    ) -> None:
        if max_candidates <= 0:
            raise ValueError(
                "max_candidates must be greater than zero."
            )

        self.max_candidates = max_candidates

    def filter(
        self,
        stocks: list[Stock],
    ) -> list[Stock]:
        unique: dict[str, Stock] = {}

        for stock in stocks:
            ticker = stock.ticker.strip().upper()

            if not ticker:
                continue

            if ticker not in unique:
                unique[ticker] = stock

        stocks_sorted = sorted(
            unique.values(),
            key=lambda stock: stock.ticker,
        )

        return stocks_sorted[
            : self.max_candidates
        ]