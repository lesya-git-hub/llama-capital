from enum import Enum


class Recommendation(str, Enum):
    RESEARCH = "RESEARCH"
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    REJECT = "REJECT"


class CommitteeDecisionType(str, Enum):
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    REJECT = "REJECT"