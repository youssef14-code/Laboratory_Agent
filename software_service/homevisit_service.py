"""
software_services/homevisit_service.py
"""

import uuid

from datetime import datetime, timezone

from models.models import Homevisit, Status, db
from software_service.base_service import BaseService


class HomeVisitService(BaseService):

    # ── list / search ─────────────────────────────────────────────────────────

    @staticmethod
    def get_all_bookings(page=1, per_page=10, search=None, status=None):
        query = Homevisit.query

        if search:
            query = query.filter(
                db.or_(
                    Homevisit.name.ilike(f'%{search}%'),
                    Homevisit.phone_number.ilike(f'%{search}%'),
                    Homevisit.reference_id.ilike(f'%{search}%'),
                )
            )

        if status:
            try:
                query = query.filter(Homevisit.status == Status(status))
            except ValueError:
                pass

        query = query.order_by(Homevisit.booking_time.desc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم العثور على الحجوزات")

    # ── single ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_visit_by_id(visit_id):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return None, "الحجز غير موجود"
        return visit, "تم العثور على الحجز"

    @staticmethod
    def get_visit_by_reference(reference_id):
        visit = Homevisit.query.filter_by(reference_id=reference_id).first()
        if not visit:
            return None, "الحجز غير موجود"
        return visit, "تم العثور على الحجز"

    # ── helper function ────────────────────────────────────────────────────────────────
    @staticmethod
    def _build_visit(name, phone_number, date, details, comes_from, address):
        return Homevisit(
            reference_id=uuid.uuid4().hex[:12].upper(),
            name=name.strip(),
            phone_number=phone_number.strip(),
            date=date,
            details=details,
            comes_from=comes_from,
            status=Status.PENDING,
            booking_time=datetime.now(timezone.utc),
            address=address
        )
    # ── create ────────────────────────────────────────────────────────────────
    @staticmethod
    def create_visit(name, phone_number, date, details, comes_from, address):
        if not name or not name.strip():
            return None, "اسم المريض مطلوب"
        if not phone_number or not phone_number.strip():
            return None, "رقم الهاتف مطلوب"
        if not address or not address.strip():
            return None, "العنوان مطلوب"
        visit = HomeVisitService._build_visit(name, phone_number, date, details, comes_from, address)
        res, msg = BaseService.commit(visit, success_msg="تم إنشاء الحجز بنجاح", error_prefix="حدث خطأ أثناء إنشاء الحجز")
        if res is None:
            visit = HomeVisitService._build_visit(name, phone_number, date, details, comes_from, address)
            return BaseService.commit(visit, success_msg="تم إنشاء الحجز بنجاح", error_prefix="حدث خطأ أثناء إنشاء الحجز")
        return res, msg
    # ── update ────────────────────────────────────────────────────────────────

    @staticmethod
    def update_visit(visit_id, name=None, phone_number=None, date=None, details=None, address=None):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return None, "الحجز غير موجود"

        if name is not None:
            visit.name = name.strip()
        if phone_number is not None:
            visit.phone_number = phone_number.strip()
        if date is not None:
            visit.date = date
        if details is not None:
            visit.details = details
        if address is not None:
            visit.address = address   
        # أي تعديل على الحجز يرجّعه Pending تلقائي
        visit.status = Status.PENDING

        return BaseService.update_commit(visit, success_msg="تم تحديث الحجز بنجاح", error_prefix="حدث خطأ أثناء تحديث الحجز")

    # ── status ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_latest_booking(sender_id: str, page_id: str = None):
        query = db.session.query(Homevisit).filter(
            Homevisit.comes_from.like(f"%:{sender_id}:%")
        )
        if page_id:
            query = query.filter(
                Homevisit.comes_from.like(f"%:{sender_id}:{page_id}")
            )
        return query.order_by(Homevisit.booking_time.desc()).first()

    @staticmethod
    def update_status(visit_id, new_status: str):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return None, "الحجز غير موجود"

        try:
            visit.status = Status(new_status)
        except ValueError:
            return None, "حالة غير صحيحة"

        return BaseService.update_commit(visit, success_msg="تم تحديث الحالة بنجاح", error_prefix="حدث خطأ أثناء تحديث الحالة")

    # ── delete ────────────────────────────────────────────────────────────────

    @staticmethod
    def delete_visit(visit_id):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return None, "الحجز غير موجود"

        return BaseService.delete(visit, success_msg="تم حذف الحجز بنجاح", error_prefix="حدث خطأ أثناء الحذف")

    # ── stats (for dashboard) ─────────────────────────────────────────────────

    @staticmethod
    def get_stats():
        total   = Homevisit.query.count()
        pending = Homevisit.query.filter_by(status=Status.PENDING).count()
        done    = Homevisit.query.filter_by(status=Status.DONE).count()
        no_show = Homevisit.query.filter_by(status=Status.NO_SHOW).count()
        return {
            "total":   total,
            "pending": pending,
            "done":    done,
            "no_show": no_show,
        }


# Backward compatibility alias
homevisitService = HomeVisitService
