"""
software_services/complaint_service.py
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from models.models import Complaint, Status, db


# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ComplaintResult:
    success: bool
    complaint: object
    message: str


# ── service ───────────────────────────────────────────────────────────────────

class ComplaintService:

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
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination, "تم العثور على الشكاوى"

    @staticmethod
    def get_complaint_by_id(complaint_id):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return ComplaintResult(False, None, "الشكوى غير موجودة")
        return ComplaintResult(True, complaint, "تم العثور على الشكوى")

    # ── stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats():
        total    = Complaint.query.count()
        pending  = Complaint.query.filter_by(status=Status.PENDING).count()
        done= Complaint.query.filter_by(status=Status.DONE).count()
        confirmed = Complaint.query.filter_by(status=Status.CONFIRMED).count()
        return {
            "total":    total,
            "pending":  pending,
            "done": done,
            "confirmed": confirmed,
        }

    # ── write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def update_status(complaint_id, new_status: str):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return ComplaintResult(False, None, "الشكوى غير موجودة")
        try:
            complaint.status = Status(new_status)
            db.session.commit()
            return ComplaintResult(True, complaint, "تم تحديث الحالة بنجاح")
        except ValueError:
            return ComplaintResult(False, None, "حالة غير صحيحة")
        except Exception as e:
            db.session.rollback()
            return ComplaintResult(False, None, f"حدث خطأ: {str(e)}")

    @staticmethod
    def delete_complaint(complaint_id):
        complaint = db.session.get(Complaint, complaint_id)
        if not complaint:
            return ComplaintResult(False, None, "الشكوى غير موجودة")
        try:
            db.session.delete(complaint)
            db.session.commit()
            return ComplaintResult(True, None, "تم حذف الشكوى بنجاح")
        except Exception as e:
            db.session.rollback()
            return ComplaintResult(False, None, f"حدث خطأ: {str(e)}")

    @staticmethod
    def create_complaint(phone_number, complaint_text, comes_from=None):
        if not phone_number or not phone_number.strip():
            return ComplaintResult(False, None, "رقم الهاتف مطلوب")
        if not complaint_text or not complaint_text.strip():
            return ComplaintResult(False, None, "نص الشكوى مطلوب")
        try:
            complaint = Complaint(
                phone_number=phone_number.strip(),
                complaint_text=complaint_text.strip(),
                comes_from=comes_from,
                status=Status.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(complaint)
            db.session.commit()
            return ComplaintResult(True, complaint, "تم تسجيل الشكوى بنجاح")
        except Exception as e:
            db.session.rollback()
            return ComplaintResult(False, None, f"حدث خطأ: {str(e)}")