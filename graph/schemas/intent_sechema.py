from enum import Enum

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    VISIT = "visit"
    INQUIRY = "inquiry"
    COMPLAINT = "complaint"
    DIRECT = "direct"
    LABRESULTS  = "labresults"


class RefinedQuery(BaseModel):

    query: str = Field(
        description="Canonical laboratory or bundle name."
    )

    aliases: list[str] = Field(
        default_factory=list,
        description="Equivalent names, abbreviations and alternative names that refer to the same laboratory test."
    )

    keywords: list[str] = Field(
        default_factory=list,
        description="Medical retrieval keywords related to the laboratory test."
    )

    description: str = Field(
        description="Short semantic description used to improve semantic retrieval."
    )

class IntentResponse(BaseModel):

    intent: IntentType

    refined_queries: list[RefinedQuery] = Field(
        default_factory=list,
        description=""
    )
    