from typing import Optional
from pydantic import BaseModel, Field


class HomevisitData(BaseModel):
    name: Optional[str] = Field(
        None, description="ONLY the patient full name."
    )
    phone_number: Optional[str] = Field(
        None, description="ONLY the exact phone digits typed by the user verbatim. NEVER autocomplete, guess, or prepend prefixes like '010' or '011'."
    )
    details: Optional[str] = Field(
        None, description="ONLY the requested lab test names (e.g. CBC, Lipid Profile)."
    )
    date: Optional[str] = Field(
        None, description="ONLY the visit appointment date (YYYY-MM-DD or as stated)."
    )
    address: Optional[str] = Field(
        None, description="Concise physical address only (never repeat phrases)."
    )


class HomevisitResponse(BaseModel):
    reply: str = Field(
        description="Conversational response to the patient in Egyptian Arabic."
    )
    test_prices: list[float] = Field(
        default_factory=list,
        description="List of prices from Retrieved Knowledge for ONLY the specific tests presented/extracted in your reply, e.g. [150.0, 250.0, 250.0]."
    )
    summary: str = Field(
        description=(
            "Persistent English conversation memory.\n\n"
            "Update this memory after every conversation turn while preserving all previously collected information.\n"
            "Never rewrite memory from scratch. Always merge new information into existing memory.\n"
            "Always preserve: Customer name, Phone number, Address, Date, Inquiries, Requested tests, and Booking progress."
        )
    )
    visit: HomevisitData = Field(
        description="Cumulative extracted booking details collected so far (from summary and current turn)."
    )
    confirmed: bool = Field(
        default=False,
        description="CRITICAL: Set to TRUE if the patient agrees to or confirms the booking summary. Set to FALSE only if details are still being collected or patient changes their mind."
    )