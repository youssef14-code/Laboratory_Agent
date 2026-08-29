from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


# ----------------------------------------------------
# Shared Item Model
# ----------------------------------------------------
class LabTestItem(BaseModel):
    name: str = Field(
        description=(
            "Standardized lab test name, EXACTLY as it appears in Verified Lab "
            "Information (the retrieved context). Never a name typed from general "
            "knowledge — if a test is not present in Verified Lab Information, "
            "it must NOT appear in this list at all."
        )
    )
    price: float | None = Field(
        default=None,
        description="Price in EGP as a numeric value if present in Verified Lab Information, otherwise null. Never invent."
    )
    preparation: str | None = Field(
        default=None,
        description="Preparation instructions if present, otherwise null."
    )


# ----------------------------------------------------
# Homevisit Models
# ----------------------------------------------------
class HomevisitData(BaseModel):
    # NOTE: هذه الحقول لازم تمثل الحالة التراكمية الكاملة المعروفة حتى الآن
    # (مش بس ما استُخرج في هذا الـ turn) — بشرط إن الـ node بيبعت للموديل
    # القيم المعروفة سابقًا كـ context ويطلب منه يحافظ عليها/يحدّثها.
    # لو الـ node مش بيعمل كده، الحقل ده لازم يتعامل معاه كـ "delta" بس،
    # ويتم الـ merge في state.py — لازم نتأكد من التصميم الفعلي في الملفين دول.
    name: Optional[str] = Field(
        None,
        description=(
            "Patient's full name (الاسم الرباعي) as stated by the client. "
            "Extract the name EXACTLY as written/spoken, without adding or inventing any part. "
            "Do NOT auto-complete missing parts and do NOT guess a father's or grandfather's name. "
            "Minimum acceptable: at least THREE parts (الاسم الثلاثي) — "
            "First name + Father's name + Grandfather's name. "
            "If the client provided only a first name and/or father's name (2 parts or fewer), "
            "extract them as-is and return them normally — validation of minimum length "
            "will be handled separately, not by you."
        )
    )
    phone_number: Optional[str] = Field(
        None,
        description="Patient phone number."
    )
    details: Optional[str] = Field(
        None,
        description=(
            "The lab test(s) or medical examination(s) the client is requesting, "
            "written exactly as the client mentioned them (in Arabic if the client used Arabic, "
            "preserving colloquial or informal names as-is — do NOT translate or formalize them). "
            "If the client mentions multiple tests, list them separated by commas "
            "(e.g., 'تحليل سكر, صورة دم كاملة, وظائف كبد'). "
            "If the client describes symptoms instead of naming a specific test "
            "(e.g., 'عايز أعمل تحليل للغدة الدرقية' or 'محتاج أطمن على الكلى'), "
            "capture the description as stated without inferring or adding test names "
            "that weren't explicitly mentioned. "
            "If no specific test or examination was mentioned in the conversation, return null."
        )
    )
    date: Optional[str] = Field(
        None,
        description="Resolved appointment date in ISO format if possible."
    )
    address: Optional[str] = Field(
        None,
        description="Patient home address for the visit, exactly as understood from the conversation."
    )


class HomevisitResponse(BaseModel):
    reply: str = Field(
        description=(
            "Conversational reply to the patient — questions asking for missing "
            "fields, confirmations, booking-status messages, etc. NEVER put test "
            "names, prices, preparation, or result times here — those go ONLY in "
            "`tests`. If `tests` is non-empty, this field must contain only the "
            "surrounding conversational text (e.g. asking for the next missing "
            "field, or the confirmation question), never the test details "
            "themselves."
        )
    )
    summary: str = Field(
        description=(
            "Updated English conversation summary, for CONTEXT/LOGGING ONLY. "
            "This field must NEVER be treated as a source of truth by any code — "
            "`visit` below is the only structured source of truth. Always keep "
            "all collected homevisit information (patient name, phone, requested "
            "tests, appointment date, confirmation status) so future turns can "
            "continue without asking again."
        )
    )
    visit: HomevisitData = Field(
        description=(
            "Structured booking information. This must represent the FULL "
            "cumulative state known so far (not just this turn) — if a field "
            "was already known from a previous turn and the user didn't "
            "contradict it, it must still be present here, not null."
        )
    )
    tests: list[LabTestItem] = Field(
        default_factory=list,
        description=(
            "One entry per lab test being priced/described to the patient this "
            "turn, with a confident match in Verified Lab Information. Do NOT "
            "include the 'HOME VISIT' / administrative visit-fee item here — "
            "only actual lab tests. Extract data only, never format as text."
        )
    )
    total_price: float | None = Field(
        default=None,
        description=(
            "Sum of prices in `tests` ONLY (never the home visit fee). "
            "This value is recomputed and overwritten programmatically after "
            "extraction (see model_validator below) — whatever the model "
            "outputs here is only a hint and is not trusted as-is."
        )
    )
    confirmed: bool = Field(default=False,
        description=(
            "True only if the user explicitly and unambiguously confirms the booking "
            "(e.g. نعم، تأكيد، تمام، موافق، أيوة تمام، yes, confirm). "
            "A bare acknowledgment like 'اه' alone (without an explicit confirmation word) "
            "is NOT sufficient — ask for clarification or treat as still pending."
        )
    )
    ready_to_save: bool = Field(default=False,
        description=(
            "True only if name, phone, requested tests, and appointment date "
            "are all available from the conversation."
        )
    )

    @model_validator(mode="after")
    def _recompute_total_price(self) -> "HomevisitResponse":
        """
        لا نثق بـ total_price اللي رجعه الموديل. نعيد حسابه برمجيًا من
        tests فقط — ولو أي تحليل في tests سعره None، نخلي total_price
        كله None (زي ما موضح في الوصف: "لو كل التحاليل عندها سعر مؤكد بس").
        """
        if not self.tests:
            self.total_price = None
            return self

        prices = [t.price for t in self.tests]
        if any(p is None for p in prices):
            self.total_price = None
        else:
            self.total_price = round(sum(prices), 2)

        return self