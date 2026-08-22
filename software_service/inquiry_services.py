"""
software_services/inquiry_service.py
"""

from datetime import datetime, timezone

from models.models import Inquiry, Status, db
from software_service.base_service import BaseService


class InquiryService(BaseService):

    # ── read ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_inquiries(page=1, per_page=10, search=None, status=None):
        query = Inquiry.query

        if search:
            query = query.filter(
                db.or_(
                    Inquiry.phone_number.ilike(f'%{search}%'),
                    Inquiry.comes_from.ilike(f'%{search}%'),
                    Inquiry.services_mentioned.ilike(f'%{search}%'),
                )
            )

        if status:
            try:
                query = query.filter(Inquiry.status == Status(status))
            except ValueError:
                pass

        query = query.order_by(Inquiry.created_at.desc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم العثور على الاستفسارات")

    @staticmethod
    def get_inquiry_by_id(inquiry_id):
        inquiry = db.session.get(Inquiry, inquiry_id)
        if not inquiry:
            return None, "الاستفسار غير موجود"
        return inquiry, "تم العثور على الاستفسار"

    @staticmethod
    def get_pending_count():
        return Inquiry.query.filter_by(status=Status.PENDING).count()

    # ── stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats():
        total      = Inquiry.query.count()
        pending    = Inquiry.query.filter_by(status=Status.PENDING).count()
        done       = Inquiry.query.filter_by(status=Status.DONE).count()
        confirmed  = Inquiry.query.filter_by(status=Status.CONFIRMED).count()

        # average confidence score for inquiries that have one
        from sqlalchemy import func
        avg_conf = db.session.query(
            func.avg(Inquiry.confidence_score)
        ).filter(Inquiry.confidence_score.isnot(None)).scalar()

        return {
            "total":     total,
            "pending":   pending,
            "done":      done,
            "confirmed": confirmed,
            "avg_conf":  round((avg_conf or 0) * 100, 1),   # 0-100 %
        }

    # ── write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def save_inquiry(
        laboratory_id: int,
        phone_number: str,
        comes_from: str,
        prescription_img: str = None,
        ocr_extracted_text: str = None,
        confidence_score: float = None,
        services_mentioned: str = None,
        status: Status = Status.PENDING,
    ):
        if not laboratory_id:
            return None, "المعمل مطلوب"
        if not phone_number or not phone_number.strip():
            return None, "رقم الهاتف مطلوب"
        if not comes_from or not comes_from.strip():
             return None, "مصدر الاستفسار مطلوب"

        """Saves prescription inquiry to the database."""
        inquiry = Inquiry(
            laboratory_id=laboratory_id,
            phone_number=phone_number,
            comes_from=comes_from,
            prescription_img=prescription_img,
            ocr_extracted_text=ocr_extracted_text,
            confidence_score=confidence_score,
            services_mentioned=services_mentioned,
            status=status,
            created_at=datetime.now(timezone.utc),
        )
        return BaseService.commit(inquiry, success_msg="تم حفظ الاستفسار بنجاح", error_prefix="حدث خطأ أثناء حفظ الاستفسار")

    @staticmethod
    def update_status(inquiry_id, new_status: str):
        inquiry = db.session.get(Inquiry, inquiry_id)
        if not inquiry:
            return None, "الاستفسار غير موجود"

        try:
            inquiry.status = Status(new_status)
        except ValueError:
            return None, "حالة غير صحيحة"

        return BaseService.update_commit(inquiry, success_msg="تم تحديث الحالة بنجاح", error_prefix="حدث خطأ أثناء تحديث الحالة")

    @staticmethod
    def delete_inquiry(inquiry_id):
        inquiry = db.session.get(Inquiry, inquiry_id)
        if not inquiry:
            return None, "الاستفسار غير موجود"

        return BaseService.delete(inquiry, success_msg="تم حذف الاستفسار بنجاح", error_prefix="حدث خطأ أثناء الحذف")
