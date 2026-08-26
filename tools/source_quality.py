from models.source_quality import SourceType


SOURCE_TYPES = {
    "Reuters": SourceType.PRIMARY_NEWS,
    "Bloomberg": SourceType.PRIMARY_NEWS,
    "Associated Press": SourceType.PRIMARY_NEWS,

    "Yahoo": SourceType.SECONDARY_NEWS,
    "Benzinga": SourceType.SECONDARY_NEWS,

    "SeekingAlpha": SourceType.COMMENTARY,

    "Rocket Lab": SourceType.OFFICIAL,
    "SEC": SourceType.OFFICIAL,
}


SOURCE_QUALITY = {
    SourceType.OFFICIAL: 10.0,
    SourceType.PRIMARY_NEWS: 9.5,
    SourceType.SECONDARY_NEWS: 7.0,
    SourceType.COMMENTARY: 5.0,
    SourceType.UNKNOWN: 4.0,
}


def get_source_type(source: str) -> SourceType:
    return SOURCE_TYPES.get(
        source,
        SourceType.UNKNOWN,
    )


def get_source_quality(source: str) -> float:
    source_type = get_source_type(source)

    return SOURCE_QUALITY[source_type]