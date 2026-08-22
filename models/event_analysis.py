from enum import Enum

from models.base import LCModel
from models.event_cluster import EventCluster

class EventType(str, Enum):
    CONTRACT = "CONTRACT"
    EARNINGS = "EARNINGS"
    GUIDANCE = "GUIDANCE"
    ACQUISITION = "ACQUISITION"
    PRODUCT = "PRODUCT"
    REGULATORY = "REGULATORY"
    PARTNERSHIP = "PARTNERSHIP"
    ANALYST_RATING = "ANALYST_RATING"
    FINANCING = "FINANCING"
    MANAGEMENT = "MANAGEMENT"
    OTHER = "OTHER"


class ImpactDirection(str, Enum):
    STRONGLY_POSITIVE = "STRONGLY_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    STRONGLY_NEGATIVE = "STRONGLY_NEGATIVE"
    MIXED = "MIXED"

class ArticleKind(str, Enum):
    CORPORATE_EVENT = "CORPORATE_EVENT"
    ANALYST_COMMENTARY = "ANALYST_COMMENTARY"
    VALUATION_COMMENTARY = "VALUATION_COMMENTARY"
    MARKET_COMMENTARY = "MARKET_COMMENTARY"
    INVESTOR_FLOW = "INVESTOR_FLOW"
    OTHER = "OTHER"

class EventAnalysis(LCModel):
    cluster: EventCluster

    event_type: EventType
    article_kind: ArticleKind
    is_primary_event: bool

    importance_score: float
    source_quality_score: float
    corroboration_score: float
    strategic_relevance_score: float

    impact_direction: ImpactDirection
    impact_score: float

    opportunity_score: float

    rationale: list[str]
