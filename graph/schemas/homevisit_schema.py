from typing import Optional
from pydantic import BaseModel, Field


class HomevisitData(BaseModel):
    name: Optional[str] = Field(
        None,
        description=(
            "The patient's FULL 4-PART NAME (الاسم رباعي بالكامل - at least 4 names/words, e.g. 'يوسف حازم أحمد محمود'). "
            "CRITICAL: If the user provides fewer than 4 names (e.g. only a first name 'يوسف' or double name 'يوسف حازم'), "
            "leave this as None so the assistant prompts them to complete their full 4-part name."
        ),
    )
    age: Optional[int] = Field(
        None, description="STRICTLY REQUIRED: Patient age in years as an integer (e.g. 25, 40). Extract digits only."
    )
    phone_number1: Optional[str] = Field(
        None, description="STRICTLY REQUIRED: Primary contact phone digits typed by the user verbatim."
    )
    phone_number2: Optional[str] = Field(
        None, description="STRICTLY REQUIRED: Secondary / alternative contact phone digits typed by the user verbatim."
    )
    details: Optional[str] = Field(
        None, description="ONLY the requested lab test names (e.g. CBC, Lipid Profile)."
    )
    date: Optional[str] = Field(
        None, description="ONLY the visit appointment date (YYYY-MM-DD or as stated)."
    )
    address: Optional[str] = Field(
        None, description="Detailed physical address ONLY (Must include: Area/Street, Building number/name, Floor, Apartment, and Landmark if any). Set to null if the user provided only a vague or incomplete location."
    )


class HomevisitResponse(BaseModel):
    reply: str = Field(
        description="Conversational response to the patient in Egyptian Arabic."
    )
    total_price: float | None = Field(
        default=None,
        description=(
            "The total estimated price calculated "
            "directly by the LLM. "
            "Never include home visit fees. "
            "Return null if pricing is incomplete."
        )
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