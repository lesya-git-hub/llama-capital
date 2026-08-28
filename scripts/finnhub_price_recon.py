import os
import time
from datetime import datetime, timedelta

import finnhub
from dotenv import load_dotenv


load_dotenv()


def main() -> None:
    api_key = os.getenv("FINNHUB_API_KEY")

    if not api_key:
        raise ValueError(
            "FINNHUB_API_KEY is missing."
        )

    client = finnhub.Client(
        api_key=api_key
    )

    ticker = "RKLB"

    end = datetime.now()
    start = end - timedelta(days=365)

    candles = client.stock_candles(
        ticker,
        "D",
        int(start.timestamp()),
        int(end.timestamp()),
    )

    print("Status:", candles.get("s"))

    closes = candles.get("c", [])
    timestamps = candles.get("t", [])

    print("Daily closes:", len(closes))

    if closes:
        print("First close:", closes[0])
        print("Last close:", closes[-1])

    if timestamps:
        print(
            "First date:",
            datetime.fromtimestamp(
                timestamps[0]
            ).date(),
        )
        print(
            "Last date:",
            datetime.fromtimestamp(
                timestamps[-1]
            ).date(),
        )


if __name__ == "__main__":
    main()