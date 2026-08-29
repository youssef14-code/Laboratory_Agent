from dataclasses import dataclass
from typing import Optional, Any
from langchain_core.tools import tool

from graph.utils import get_platform_name
from software_service.complaint_services import ComplaintService


@dataclass
class ComplaintResult:
    success: bool
    message: str
    complaint: Optional[Any] = None


@tool
def save_complaint_tool(
    phone: str,
    complaint_text: str,
    comes_from: str = "unknown",
) -> ComplaintResult:
    """
    Save a user complaint to the database.
    Returns a ComplaintResult.
    """
    platform_name = get_platform_name(comes_from)

    complaint, message = ComplaintService.create_complaint(
        phone_number=phone,
        complaint_text=complaint_text,
        comes_from=platform_name,
    )

    is_success = complaint is not None

    return ComplaintResult(
        success=is_success,
        message=message,
        complaint=complaint,
    )