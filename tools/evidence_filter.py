from models.evidence import Evidence


HIGH_VALUE_KEYWORDS = {
    "contract",
    "awarded",
    "acquisition",
    "acquires",
    "merger",
    "partnership",
    "approval",
    "launch",
    "guidance",
    "earnings",
    "revenue",
    "backlog",
    "order",
    "investment",
    "expansion",
}


def calculate_relevance(item: Evidence) -> int:
    headline = item.headline.lower()

    score = 0

    ticker = item.stock.ticker.lower()
    company = item.stock.company.lower()

    if ticker in headline:
        score += 3

    if company in headline:
        score += 4

    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword in headline:
            score += 2

    return score


def filter_evidence(
    evidence_items: list[Evidence],
    max_items: int = 10,
) -> list[Evidence]:
    unique_items: list[Evidence] = []
    seen_headlines: set[str] = set()

    for item in evidence_items:
        headline = item.headline.strip()

        if not headline:
            continue

        normalized = headline.lower()

        if normalized in seen_headlines:
            continue

        seen_headlines.add(normalized)

        if calculate_relevance(item) == 0:
            continue

        unique_items.append(item)

    ranked_items = sorted(
        unique_items,
        key=calculate_relevance,
        reverse=True,
    )

    return ranked_items[:max_items]