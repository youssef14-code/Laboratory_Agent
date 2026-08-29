from typing import Optional

from pydantic import BaseModel, Field


class ComplaintData(BaseModel):
    phone: Optional[str] = Field(
        None,
        description="User phone number. Do not invent a phone number."
    )

    complaint_text: Optional[str] = Field(
        None,
        description="The user's complaint exactly as understood from the conversation."
    )


class ComplaintResponse(BaseModel):

    reply: str = Field(
        description="Reply that will be sent to the user."
    )

    summary: str = Field(
        description=(
            "Updated English conversation summary. "
            "Always preserve all previously collected information "
            "(customer name, phone, booking information, complaint information, "
            "confirmation status, and any other relevant conversation details) "
            "so future turns can continue without asking for the same information again."
        )
    )

    complaint: ComplaintData = Field(
        description="Structured complaint information extracted from this turn."
    )

    confirmed: bool = Field(
        description=(
            "True only if the user explicitly confirms that they want "
            "to submit the complaint "
            "(e.g. تمام، ماشي، اه، أيوة، yes, submit, confirm)."
        )
    )

    ready_to_save: bool = Field(
        description=(
            "True only if the user's phone number and complaint "
            "text are both available from the conversation."
        )
    )