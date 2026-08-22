import os

from dotenv import load_dotenv
from openai import OpenAI

from models.event_analyst_output import EventAnalystOutput
from models.event_cluster import EventCluster


load_dotenv()


class OpenAIEventProvider:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
        )

        self.model = os.getenv(
            "LLAMA_EVENT_MODEL",
            "gpt-5.4-mini",
        )

    def analyze(
        self,
        cluster: EventCluster,
    ) -> EventAnalystOutput:
        evidence_text = "\n\n".join(
            (
                f"Source: {item.source}\n"
                f"Headline: {item.headline}\n"
                f"Summary: {item.content or 'No summary available.'}"
            )
            for item in cluster.evidence_items
        )

        prompt = f"""
You are an event-analysis component inside an investment research system.

Analyze ONLY the supplied evidence.
Do not assume facts that are not present in the evidence.

Company: {cluster.stock.company}
Ticker: {cluster.stock.ticker}

Evidence:
{evidence_text}

Determine:
- the primary event type
- the article kind
- whether this evidence primarily reports a new corporate event
- likely directional impact on the company
- impact magnitude from -10 to +10
- materiality from 0 to 10
- a concise factual summary
- bull case
- bear case
- uncertainties
- concise rationale

Article kind definitions:

CORPORATE_EVENT:
The evidence primarily reports a new company event such as a contract,
acquisition, earnings release, guidance change, regulatory decision,
financing, partnership, management change, or product milestone.

ANALYST_COMMENTARY:
The primary purpose is an analyst rating, price target, or research opinion.

VALUATION_COMMENTARY:
The primary purpose is arguing that the stock is undervalued or overvalued.

MARKET_COMMENTARY:
The primary purpose is discussing price movement or general market reaction.

INVESTOR_FLOW:
The primary purpose is reporting an investor, fund, ETF, or insider
buying or selling.

OTHER:
Use when none of the categories above clearly applies.

Classification precedence rules:

Determine the PRIMARY PURPOSE of the article, not merely the business events
mentioned inside it.

If the headline or evidence primarily argues that a stock is undervalued,
overvalued, fairly valued, cheap, expensive, or discusses intrinsic/fair value,
classify it as VALUATION_COMMENTARY and set is_primary_event=False.

If the primary purpose is an analyst rating, price target, upgrade, downgrade,
or investment thesis, classify it as ANALYST_COMMENTARY and set
is_primary_event=False.

If the primary purpose is explaining why the stock price rose or fell,
classify it as MARKET_COMMENTARY and set is_primary_event=False.

A commentary article can refer to a real contract, acquisition, earnings result,
or product milestone without itself becoming a CORPORATE_EVENT.

Use CORPORATE_EVENT only when the article's primary purpose is reporting the
new corporate event itself.

Examples:

"Company wins $50M government contract"
→ CORPORATE_EVENT
→ CONTRACT
→ is_primary_event=True

"Company may be 30% undervalued after recent contract wins"
→ VALUATION_COMMENTARY
→ CONTRACT may be the underlying event type
→ is_primary_event=False

Important:
Opportunity and materiality are not the same as bullishness.
A highly material negative event should receive high materiality
and a negative impact score.
"""

        response = self.client.responses.parse(
            model=self.model,
            input=prompt,
            text_format=EventAnalystOutput,
        )

        message = response.output[0]

        if message.type != "message":
            raise RuntimeError("Unexpected OpenAI response type.")

        content = message.content[0]

        if content.type != "output_text":
            raise RuntimeError("Unexpected OpenAI content type.")

        if content.parsed is None:
            raise RuntimeError(
                "OpenAI response could not be parsed."
            )

        return content.parsed