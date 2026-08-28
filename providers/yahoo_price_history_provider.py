from datetime import datetime, timedelta

import yfinance as yf

from models.stock import Stock
from providers.base_price_history_provider import (
    BasePriceHistoryProvider,
)


class YahooPriceHistoryProvider(
    BasePriceHistoryProvider
):
    def fetch_daily_closes(
        self,
        stock: Stock,
        days: int = 365,
    ) -> list[float]:
        end = datetime.now()
        start = end - timedelta(days=days)

        data = yf.download(
            stock.ticker,
            start=start,
            end=end,
            progress=False,
            auto_adjust=True,
        )

        if data.empty:
            raise ValueError(
                f"No price history found for "
                f"{stock.ticker}."
            )

        closes = data["Close"]

        return [
            float(value)
            for value in closes.to_numpy().flatten()
        ]