from models.base import LCModel
from models.stock import Stock
from models.evidence import Evidence
from models.event_analysis import ArticleKind, ImpactDirection


class Opportunity(LCModel):
    stock: Stock

    event: str

    importance: int

    evidence: Evidence

    opportunity_score: float

    impact_direction: ImpactDirection

    impact_score: float

    materiality_score: float

    source_quality_score: float

    corroboration_score: float

    strategic_relevance_score: float

    article_kind: ArticleKind

    is_primary_event: bool