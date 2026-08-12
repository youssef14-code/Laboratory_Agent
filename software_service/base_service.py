from models.models import db
class BaseService:

    @staticmethod
    def paginate(query, page=1, per_page=10, success_msg="تم الجلب بنجاح"):
        """Generic query pagination wrapper."""
        try:
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            return pagination, success_msg
        except Exception as e:
            return None, f"حدث خطأ أثناء الجلب: {str(e)}"

    @staticmethod
    def commit(entity, success_msg="تم حفظ البيانات بنجاح", error_prefix="حدث خطأ أثناء الحفظ"):
        """Generic DB commit wrapper with automatic rollback."""
        try:
            db.session.add(entity)
            db.session.commit()
            return entity, success_msg
        except Exception as e:
            db.session.rollback()
            return None, f"{error_prefix}: {str(e)}"

    @staticmethod
    def update_commit(entity, success_msg="تم التحديث بنجاح", error_prefix="حدث خطأ أثناء التحديث"):
        """Generic DB update commit wrapper with automatic rollback."""
        try:
            db.session.commit()
            return entity, success_msg
        except Exception as e:
            db.session.rollback()
            return None, f"{error_prefix}: {str(e)}"

    @staticmethod
    def delete(entity, success_msg="تم الحذف بنجاح", error_prefix="حدث خطأ أثناء الحذف"):
        """Generic DB delete wrapper with automatic rollback."""
        try:
            db.session.delete(entity)
            db.session.commit()
            return entity, success_msg
        except Exception as e:
            db.session.rollback()
            return None, f"{error_prefix}: {str(e)}"