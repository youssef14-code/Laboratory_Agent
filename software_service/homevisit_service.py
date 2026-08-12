"""
software_services/booking_service.py
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from models.models import Homevisit, Status, db


# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class homevisitResult:
    success: bool
    visit: object
    message: str


# ── service ───────────────────────────────────────────────────────────────────

class homevisitService:

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
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination, "تم العثور على الحجوزات"

    # ── single ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_visit_by_id(visit_id):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return None, "الحجز غير موجود"
        return  visit, "تم العثور على الحجز"

    @staticmethod
    def get_visit_by_reference(reference_id):
        visit = Homevisit.query.filter_by(reference_id=reference_id).first()
        if not visit:
            return None, "الحجز غير موجود"
        return visit, "تم العثور على الحجز"

    # ── create ────────────────────────────────────────────────────────────────

    @staticmethod
    def create_visit(name, phone_number, date=None, details=None, comes_from=None,address=None, time=None):
        if not name or not name.strip():
            return homevisitResult(False, None, "اسم المريض مطلوب")
        if not phone_number or not phone_number.strip():
            return homevisitResult(False, None, "رقم الهاتف مطلوب")
        reference_id = uuid.uuid4().hex[:12].upper()

        try:
            visit = Homevisit(
                reference_id=reference_id,
                name=name.strip(),
                phone_number=phone_number.strip(),
                date=date,
                details=details,
                comes_from=comes_from,
                status=Status.PENDING,
                booking_time=datetime.now(timezone.utc),
                address=address,
                time=time,

            )
            db.session.add(visit)
            db.session.commit()
            return homevisitResult(True, visit, "تم إنشاء الحجز بنجاح")
        except Exception as e:
            db.session.rollback()
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError):
                
                reference_id = uuid.uuid4().hex[:12].upper()
                try:
                    visit = Homevisit(
                        reference_id=reference_id,
                        name=name.strip(),
                        phone_number=phone_number.strip(),
                        date=date,
                        details=details,
                        comes_from=comes_from,
                        status=Status.PENDING,
                        booking_time=datetime.now(timezone.utc),
                        address=address,

                    )
                    db.session.add(visit)
                    db.session.commit()
                    return homevisitResult(True, visit, "تم إنشاء الحجز بنجاح")
                except Exception as ex:
                    db.session.rollback()
                    return homevisitResult(False, None, f"حدث خطأ أثناء إنشاء الحجز: {str(ex)}")
            return homevisitResult(False, None, f"حدث خطأ أثناء إنشاء الحجز: {str(e)}")

    # ── update ────────────────────────────────────────────────────────────────

    @staticmethod
    def update_visit(visit_id, name=None, phone_number=None, date=None, details=None, address=None,time=None):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return homevisitResult(False, None, "الحجز غير موجود")

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
        if time is not None:
            visit.time = time    

        # أي تعديل على الحجز يرجّعه Pending تلقائي، مهما كانت حالته قبل كده
        visit.status = Status.PENDING

        try:
            db.session.commit()
            return homevisitResult(True, visit, "تم تحديث الحجز بنجاح")
        except Exception as e:
            db.session.rollback()
            return homevisitResult(False, None, f"حدث خطأ أثناء تحديث الحجز: {str(e)}")
    # ── status ────────────────────────────────────────────────────────────────

    # homevisit_service.py

    
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
            return homevisitResult(False, None, "الحجز غير موجود")

        try:
            visit.status = Status(new_status)
            db.session.commit()
            return homevisitResult(True,visit, "تم تحديث الحالة بنجاح")
        except ValueError:
            return homevisitResult(False, None, "حالة غير صحيحة")
        except Exception as e:
            db.session.rollback()
            return homevisitResult(False, None, f"حدث خطأ: {str(e)}")

    # ── delete ────────────────────────────────────────────────────────────────

    @staticmethod
    def delete_visit(visit_id):
        visit = db.session.get(Homevisit, visit_id)
        if not visit:
            return homevisitResult(False, None, "الحجز غير موجود")

        try:
            db.session.delete(visit)
            db.session.commit()
            return homevisitResult(True, visit, "تم حذف الحجز بنجاح")
        except Exception as e:
            db.session.rollback()
            return homevisitResult(False, None, f"حدث خطأ أثناء الحذف: {str(e)}")

    # ── stats (for dashboard) ─────────────────────────────────────────────────

    @staticmethod
    def get_stats():
        total      = Homevisit.query.count()
        pending    = Homevisit.query.filter_by(status=Status.PENDING).count()
        done  = Homevisit.query.filter_by(status=Status.DONE).count()
        no_show    = Homevisit.query.filter_by(status=Status.NO_SHOW).count()
        return {
            "total":    total,
            "pending":  pending,
            "done": done,
            "no_show":  no_show,
        }