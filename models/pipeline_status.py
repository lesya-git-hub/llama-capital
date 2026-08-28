from enum import Enum


class PipelineStatus(str, Enum):
    NO_ACTION = "NO_ACTION"
    POLICY_BLOCK = "POLICY_BLOCK"
    RESEARCH_COMPLETED = "RESEARCH_COMPLETED"