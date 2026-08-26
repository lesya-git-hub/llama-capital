from enum import Enum


class SourceType(str, Enum):
    OFFICIAL = "OFFICIAL"
    PRIMARY_NEWS = "PRIMARY_NEWS"
    SECONDARY_NEWS = "SECONDARY_NEWS"
    COMMENTARY = "COMMENTARY"
    UNKNOWN = "UNKNOWN"