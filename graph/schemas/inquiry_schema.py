from pydantic import BaseModel, Field


class InquiryResponse(BaseModel):

    reply: str = Field(
        description=(
            "Reply that will be sent to the user. "
            "Keep replies short, clear, professional, and suitable for chat. "
            "if you list a labs, don't play with formatting"
        )
    )

    summary: str = Field(
        description=(
            "Persistent English conversation memory.\n\n"

            "Update this memory after every conversation turn while preserving "
            "all previously collected information.\n\n"

            "Never rewrite the memory from scratch.\n"
            "Never remove valid information unless the user explicitly changes it.\n"
            "Always merge new information into the existing memory.\n\n"

            "Always preserve important information including:\n"
            "- Customer name\n"
            "- Phone number\n"
            "- Previous laboratory inquiries\n"
            "- Laboratory tests discussed or recommended\n"
            "- Laboratory tests the user is interested in booking\n"
            "- Existing booking information and booking progress\n"
            "- Existing complaint information and complaint progress\n"
            "- Any important preferences or conversation context\n\n"

            "If the user asks about additional laboratory tests, append them "
            "to the conversation memory instead of replacing previous inquiries.\n\n"

            "If the user later decides to book laboratory tests, keep the "
            "previous inquiry context so the booking flow can continue naturally "
            "without asking which laboratory tests they wanted again.\n\n"

            "If information changes, update only the affected part while keeping "
            "everything else unchanged.\n\n"

            "Write the memory in natural conversational English, not JSON or "
            "key-value format."
        )
    )