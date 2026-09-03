import os
import time

import requests
import finnhub
from dotenv import load_dotenv

from models.market_snapshot import MarketSnapshot
from models.stock import Stock
from providers.base_market_data_provider import (
    BaseMarketDataProvider,
)
from providers.yahoo_price_history_provider import (
    YahooPriceHistoryProvider,
)
from tools.technical_indicators import calculate_ema


load_dotenv()


class FinnhubMarketDataProvider(
    BaseMarketDataProvider
):
    def __init__(
        self,
        client=None,
        price_history_provider=None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            api_key = os.getenv(
                "FINNHUB_API_KEY"
            )

            if not api_key:
                raise ValueError(
                    "FINNHUB_API_KEY is missing."
                )

            self.client = finnhub.Client(
                api_key=api_key
            )

        self.price_history_provider = (
            price_history_provider
            or YahooPriceHistoryProvider()
        )

    def _with_retry(
        self,
        operation,
        *args,
        **kwargs,
    ):
        last_error = None

        for attempt in range(3):
            try:
                return operation(
                    *args,
                    **kwargs,
                )

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as error:
                last_error = error

            except Exception as error:
                message = str(error)

                retryable = any(
                    code in message
                    for code in (
                        "429",
                        "500",
                        "502",
                        "503",
                        "504",
                        "timed out",
                        "Read timed out",
                    )
                )

                if not retryable:
                    raise

                last_error = error

            if attempt < 2:
                time.sleep(
                    2 ** attempt
                )

        if last_error is not None:
            raise last_error

        raise RuntimeError(
            "Finnhub operation failed without an error."
        )
    
    def fetch(
        self,
        stock: Stock,
    ) -> MarketSnapshot:
        profile = self._with_retry(
            self.client.company_profile2,
            symbol=stock.ticker,
        )

        quote = self._with_retry(
            self.client.quote,
            stock.ticker,
        )

        financials = self._with_retry(
            self.client.company_basic_financials,
            stock.ticker,
            "all",
        )

        metrics = financials.get(
            "metric",
            {},
        )

        market_cap_million = profile.get(
            "marketCapitalization"
        )

        revenue_growth = metrics.get(
            "revenueGrowthTTMYoy"
        )

        debt_to_equity = metrics.get(
            "totalDebt/totalEquityQuarterly"
        )

        current_price = quote.get("c")

        if market_cap_million is None:
            raise ValueError(
                "Finnhub market capitalization "
                "is unavailable."
            )

        if revenue_growth is None:
            raise ValueError(
                "Finnhub revenue growth "
                "is unavailable."
            )

        if debt_to_equity is None:
            raise ValueError(
                "Finnhub debt-to-equity "
                "is unavailable."
            )

        if current_price is None:
            raise ValueError(
                "Finnhub current price "
                "is unavailable."
            )

        closes = (
            self.price_history_provider
            .fetch_daily_closes(
                stock,
                days=365,
            )
        )

        ema_200 = calculate_ema(
            closes,
            period=200,
        )

        return MarketSnapshot(
            stock=stock,
            market_cap_billion=(
                float(market_cap_million)
                / 1000
            ),
            revenue_growth_percent=float(
                revenue_growth
            ),
            debt_to_equity=float(
                debt_to_equity
            ),
            price=float(
                current_price
            ),
            ema_200=round(
                ema_200,
                2,
            ),
            above_200_ema=(
                float(current_price)
                > ema_200
            ),
            source="Finnhub + Yahoo",
        )