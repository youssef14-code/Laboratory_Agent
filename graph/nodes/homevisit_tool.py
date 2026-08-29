from dataclasses import dataclass
from typing import Optional, Any
from langchain_core.tools import tool

from graph.utils import get_platform_name
from software_service.homevisit_service import HomeVisitService


@dataclass
class HomeVisitResult:
    success: bool
    message: str
    visit: Optional[Any] = None


@tool
def save_visit_tool(
    name: str,
    phone_number: str,
    date: str,
    details: str,
    address: str,
    comes_from: str = "unknown",
    branch_id: int | None = None,
) -> HomeVisitResult:
    """
    Save a confirmed appointment booking to the database.
    Returns a HomeVisitResult.
    """
    platform_name = get_platform_name(comes_from)

    # استدعاء دالة إنشاء الزيارة بدون branch_id
    res = HomeVisitService.create_visit(
        name=name,
        phone_number=phone_number,
        date=date,
        details=details,
        address=address,
        comes_from=platform_name,
    )

    # التعامل الآمن مع القيمة المرجعة
    if isinstance(res, tuple):
        visit, message = res
    else:
        visit, message = res, "تم الحفظ بنجاح"

    is_success = visit is not None

    return HomeVisitResult(
        success=is_success,
        message=message,
        visit=visit,
    )