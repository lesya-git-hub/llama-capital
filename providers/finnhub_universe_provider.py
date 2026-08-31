import os
import time

import requests
from dotenv import load_dotenv

from models.stock import Stock
from providers.base_universe_provider import (
    BaseUniverseProvider,
)


load_dotenv()


class FinnhubUniverseProvider(
    BaseUniverseProvider
):
    SYMBOLS_URL = (
        "https://finnhub.io/api/v1/stock/symbol"
    )

    ALLOWED_MICS = {
        "XNAS",
        "XNYS",
    }

    EXCLUDED_DESCRIPTION_TERMS = {
        "ACQUISITION",
        "SPAC",
        "WARRANT",
        "UNIT",
    }

    def __init__(
        self,
        timeout: int = 60,
    ) -> None:
        api_key = os.getenv(
            "FINNHUB_API_KEY"
        )

        if not api_key:
            raise ValueError(
                "FINNHUB_API_KEY is missing."
            )

        self.api_key = api_key
        self.timeout = timeout

    def _is_eligible_symbol(
        self,
        item: dict,
    ) -> bool:
        if item.get("type") != "Common Stock":
            return False

        if item.get("mic") not in self.ALLOWED_MICS:
            return False

        symbol = (
            item.get("symbol")
            or ""
        ).strip()

        description = (
            item.get("description")
            or ""
        ).upper()

        if not symbol:
            return False

        if any(
            term in description
            for term in self.EXCLUDED_DESCRIPTION_TERMS
        ):
            return False

        return True

    def fetch(self) -> list[Stock]:
        response = None

        for attempt in range(3):
            try:
                response = requests.get(
                    self.SYMBOLS_URL,
                    params={
                        "exchange": "US",
                        "token": self.api_key,
                    },
                    timeout=self.timeout,
                )

                response.raise_for_status()
                break

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ):
                if attempt == 2:
                    raise

                time.sleep(2 ** attempt)

            except requests.exceptions.HTTPError:
                if (
                    response is None
                    or response.status_code
                    not in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    or attempt == 2
                ):
                    raise

                time.sleep(2 ** attempt)

        if response is None:
            raise RuntimeError(
                "Finnhub universe request produced no response."
            )

        items = response.json()

        stocks: list[Stock] = []

        for item in items:
            if not self._is_eligible_symbol(
                item
            ):
                continue

            stocks.append(
                Stock(
                    ticker=item["symbol"],
                    company=item.get(
                        "description",
                        item["symbol"],
                    ),
                    sector="Unknown",
                    industry="Unknown",
                    exchange=item.get(
                        "mic",
                        "Unknown",
                    ),
                )
            )

        return stocks