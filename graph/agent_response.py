from dataclasses import dataclass
from typing import Optional, Any

@dataclass
class AgentResponse:
    response:        str
    intent:          Optional[str]
    visit_saved:     Optional[bool]
    complaint_saved: Optional[bool]
    inquiry_saved:   Optional[bool]
    labresults_saved: Optional[bool]
    usage:           dict
    visit_reference: Optional[str] = None
    booking_pdf: Optional[bytes] = None
    @staticmethod
    def from_result(result: dict) -> "AgentResponse":
        usage = {
            "intent":      result.get("intent_usage")     or {},
            "retrieval":   result.get("retrieval_usage")   or {},  # كانت lab_info_usage غلط
            "booking":     result.get("booking_usage")     or {},
            "complaint":   result.get("complaint_usage")   or {},
            "direct":      result.get("direct_usage")      or {},
            "inquiry":     result.get("inquiry_usage")     or {},
            "labresults":  result.get("labresults_usage")  or {},  # لو اتضافت للـ state لاحقًا
        }

        return AgentResponse(
            response         = result.get("response") or "",
            intent           = result.get("intent"),
            visit_saved      = result.get("visit_saved"),
            complaint_saved  = result.get("complaint_saved"),
            inquiry_saved    = result.get("inquiry_saved"),
            labresults_saved = result.get("labresults_saved"),
            usage            = usage,
            visit_reference=result.get("visit_reference"),
            booking_pdf=result.get("booking_pdf"),
        )

    def to_dict(self) -> dict:
        return {
            "response":         self.response,
            "intent":           self.intent,
            "visit_saved":      self.visit_saved,
            "complaint_saved":  self.complaint_saved,
            "inquiry_saved":    self.inquiry_saved,
            "labresults_saved": self.labresults_saved,
            "usage":            self.usage,
            "visit_reference":  self.visit_reference,
            "booking_pdf":      self.booking_pdf is not None,  # إرجاع True/False بدل البايتات نفسها
        }