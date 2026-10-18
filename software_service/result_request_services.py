import logging
from datetime import datetime, timedelta, timezone

from models.models import ResultRequest, Status, db
from software_service.base_service import BaseService

logger = logging.getLogger(__name__)


class ResultRequestService(BaseService):
    DEDUP_HOURS = 24

    @staticmethod
    def create_request(user_identity, laboratory_id=None):
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(
                hours=ResultRequestService.DEDUP_HOURS
            )
            existing = (
                ResultRequest.query.filter_by(
                    user_identity=user_identity,
                    status=Status.PENDING,
                )
                .filter(ResultRequest.created_at >= cutoff)
                .order_by(ResultRequest.created_at.desc())
                .first()
            )
            if existing:
                return existing, False

            result_request = ResultRequest(
                user_identity=user_identity,
                laboratory_id=laboratory_id,
                status=Status.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(result_request)
            db.session.commit()
            return result_request, True
        except Exception:
            db.session.rollback()
            logger.exception("Failed to create lab result request")
            return None, False

    @staticmethod
    def get_all(page=1, per_page=10, search=None, status=None):
        query = ResultRequest.query

        if search:
            query = query.filter(ResultRequest.user_identity.ilike(f"%{search}%"))

        if status:
            try:
                query = query.filter(ResultRequest.status == Status(status))
            except (TypeError, ValueError):
                pass

        query = query.order_by(ResultRequest.created_at.desc())
        pagination, _ = BaseService.paginate(
            query,
            page=page,
            per_page=per_page,
            success_msg="تم العثور على طلبات النتائج",
        )
        return pagination

    @staticmethod
    def update_status(request_id, new_status):
        try:
            status = Status(new_status)
        except (TypeError, ValueError):
            return None, "حالة غير صحيحة"

        if status not in (Status.PENDING, Status.DONE):
            return None, "حالة غير صحيحة"

        try:
            result_request = db.session.get(ResultRequest, request_id)
            if not result_request:
                return None, "طلب النتائج غير موجود"

            result_request.status = status
            return BaseService.update_commit(
                result_request,
                success_msg="تم تحديث الحالة بنجاح",
                error_prefix="حدث خطأ أثناء تحديث الحالة",
            )
        except Exception:
            db.session.rollback()
            logger.exception("Failed to update lab result request status")
            return None, "حدث خطأ أثناء تحديث الحالة"

    @staticmethod
    def delete(request_id):
        try:
            result_request = db.session.get(ResultRequest, request_id)
            if not result_request:
                return None, "طلب النتائج غير موجود"

            return BaseService.delete(
                result_request,
                success_msg="تم حذف طلب النتائج بنجاح",
                error_prefix="حدث خطأ أثناء الحذف",
            )
        except Exception:
            db.session.rollback()
            logger.exception("Failed to delete lab result request")
            return None, "حدث خطأ أثناء حذف طلب النتائج"

    @staticmethod
    def get_stats():
        try:
            return {
                "total": ResultRequest.query.count(),
                "pending": ResultRequest.query.filter_by(
                    status=Status.PENDING
                ).count(),
                "done": ResultRequest.query.filter_by(status=Status.DONE).count(),
            }
        except Exception:
            logger.exception("Failed to load lab result request stats")
            return {"total": 0, "pending": 0, "done": 0}

    @staticmethod
    def get_pending_count():
        try:
            return ResultRequest.query.filter_by(status=Status.PENDING).count()
        except Exception:
            logger.exception("Failed to count pending lab result requests")
            return 0
