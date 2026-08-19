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
        evidence_text = "\n".join(
            f"- {item.source}: {item.headline}"
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
- likely directional impact on the company
- impact magnitude from -10 to +10
- materiality from 0 to 10
- a concise factual summary
- bull case
- bear case
- uncertainties
- concise rationale

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

        return content.parsed