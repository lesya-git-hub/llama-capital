import os

import requests
from dotenv import load_dotenv


load_dotenv()


def main() -> None:
    api_key = os.getenv("FINNHUB_API_KEY")

    if not api_key:
        raise ValueError(
            "FINNHUB_API_KEY is missing."
        )

    response = requests.get(
        "https://finnhub.io/api/v1/stock/symbol",
        params={
            "exchange": "US",
            "token": api_key,
        },
        timeout=60,
    )

    response.raise_for_status()

    symbols = response.json()

    print("Symbols found:", len(symbols))

    for item in symbols[:20]:
        print(item)


if __name__ == "__main__":
    main()