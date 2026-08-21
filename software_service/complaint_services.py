"""
software_services/complaint_service.py
"""

from datetime import datetime, timezone

from models.models import Complaint, Status, db
from software_service.base_service import BaseService


class ComplaintService(BaseService):

    # ── read ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_complaints(page=1, per_page=10, search=None, status=None):
        query = Complaint.query

        if search:
            query = query.filter(
                db.or_(
                    Complaint.phone_number.ilike(f'%{search}%'),
                    Complaint.complaint_text.ilike(f'%{search}%'),
                    Complaint.comes_from.ilike(f'%{search}%'),
                )
            )

        if status:
            try:
                query = query.filter(Complaint.status == Status(status))
            except ValueError:
                pass

        query = query.order_by(Complaint.created_at.desc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم العثور على الشكاوى")

    @staticmethod
    def get_complaint_by_id(complaint_id):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return None, "الشكوى غير موجودة"
        return complaint, "تم العثور على الشكوى"

    # ── stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats():
        total     = Complaint.query.count()
        pending   = Complaint.query.filter_by(status=Status.PENDING).count()
        done      = Complaint.query.filter_by(status=Status.DONE).count()
        confirmed = Complaint.query.filter_by(status=Status.CONFIRMED).count()
        return {
            "total":     total,
            "pending":   pending,
            "done":      done,
            "confirmed": confirmed,
        }

    # ── write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def update_status(complaint_id, new_status: str):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return None, "الشكوى غير موجودة"

        try:
            complaint.status = Status(new_status)
        except ValueError:
            return None, "حالة غير صحيحة"

        return BaseService.update_commit(complaint, success_msg="تم تحديث الحالة بنجاح", error_prefix="حدث خطأ أثناء تحديث الحالة")

    @staticmethod
    def delete_complaint(complaint_id):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return None, "الشكوى غير موجودة"

        return BaseService.delete(complaint, success_msg="تم حذف الشكوى بنجاح", error_prefix="حدث خطأ أثناء الحذف")

    @staticmethod
    def create_complaint(phone_number, complaint_text, comes_from=None):
        if not phone_number or not phone_number.strip():
            return None, "رقم الهاتف مطلوب"
        if not complaint_text or not complaint_text.strip():
            return None, "نص الشكوى مطلوب"

        complaint = Complaint(
            phone_number=phone_number.strip(),
            complaint_text=complaint_text.strip(),
            comes_from=comes_from,
            status=Status.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        return BaseService.commit(complaint, success_msg="تم تسجيل الشكوى بنجاح", error_prefix="حدث خطأ أثناء تسجيل الشكوى")