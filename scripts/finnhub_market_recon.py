from pprint import pprint

import os

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

    print("=" * 100)
    print("PROFILE")
    print("=" * 100)

    profile = client.company_profile2(
        symbol=ticker
    )

    pprint(profile)

    print()
    print("=" * 100)
    print("QUOTE")
    print("=" * 100)

    quote = client.quote(ticker)

    pprint(quote)

    print()
    print("=" * 100)
    print("BASIC FINANCIALS")
    print("=" * 100)

    financials = client.company_basic_financials(
        ticker,
        "all",
    )

    metric = financials.get(
        "metric",
        {},
    )

    print("Available metric keys:")

    for key in sorted(metric):
        print(
            key,
            "=",
            metric[key],
        )


if __name__ == "__main__":
    main()