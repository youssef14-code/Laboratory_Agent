import logging
from dataclasses import dataclass
from typing import Optional, Any
from langchain_core.tools import tool

from software_service.homevisit_service import HomeVisitService

logger = logging.getLogger(__name__)


@dataclass
class HomeVisitResult:
    success: bool
    message: str
    visit: Optional[Any] = None


@tool
def save_visit_tool(
    name: str,
    phone_number: str,
    address: str,
    details: str,
    date: str,
    comes_from: str = "unknown",
) -> HomeVisitResult:
    """
    Saves a fully collected and confirmed home visit booking to the database.
    
    All 5 main fields (name, phone_number, address, details, date) are strictly required.
    Returns a HomeVisitResult with success=True and the saved visit object upon success.
    """
    try:
        # إنشاء الحجز في قاعدة البيانات
        visit, message = HomeVisitService.create_visit(
            name=name.strip(),
            phone_number=phone_number.strip(),
            date=str(date).strip(),
            details=details.strip(),
            address=address.strip(),
            comes_from=comes_from.strip(),
        )

        is_success = visit is not None

        if is_success:
            logger.info("Successfully saved Homevisit reference=%s for patient=%s", visit.reference_id, name)
        else:
            logger.warning("Failed to save Homevisit for patient=%s: %s", name, message)

        return HomeVisitResult(
            success=is_success,
            message=message,
            visit=visit,
        )

    except Exception as e:
        logger.error("Exception in save_visit_tool for patient=%s: %s", name, e)
        return HomeVisitResult(
            success=False,
            message=f"حدث خطأ غير متوقع أثناء حفظ الحجز: {str(e)}",
            visit=None,
        )