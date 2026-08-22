from models.models import Laboratory, db
from software_service.base_service import BaseService

class LaboratoryService(BaseService):

    @staticmethod
    def get_current_laboratory_id():
        """Get default laboratory ID or create a default lab record if none exists."""
        lab = Laboratory.query.first()
        if lab:
            return lab.id
        new_lab = Laboratory(name="المعمل الرئيسي", info="معمل تحاليل رئيسي")
        saved_lab, msg = BaseService.commit(new_lab, success_msg="تم إنشاء المعمل الافتراضي", error_prefix="حدث خطأ أثناء إنشاء المعمل الافتراضي")
        if not saved_lab:
            raise ValueError(msg)
        return saved_lab.id

    @staticmethod
    def get_all_laboratories(page=1, per_page=10, search=None):
        """Get paginated list of laboratories with optional search."""
        query = Laboratory.query

        if search:
            query = query.filter(
                (Laboratory.name.ilike(f"%{search}%")) 
                
            )

        query = query.order_by(Laboratory.id.desc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم جلب معامل التحاليل بنجاح")

    @staticmethod
    def get_laboratory_by_id(lab_id):
        """Get a single laboratory by ID."""
        lab = db.session.get(Laboratory, lab_id)
        if not lab:
            return None, "المعمل غير موجود"
        return lab, "تم العثور على المعمل"

    @staticmethod
    def create_laboratory(name, info=None):
        """Create a new laboratory."""
        if not name or not name.strip():
            return None, "اسم المعمل مطلوب"

        lab = Laboratory(
            name=name.strip(),
            info=info.strip() if info else ""
        )
        return BaseService.commit(lab, success_msg="تم إضافة المعمل بنجاح", error_prefix="حدث خطأ أثناء الإضافة")

    @staticmethod
    def update_laboratory(lab_id, name=None, info=None):
        """Update an existing laboratory."""
        lab = db.session.get(Laboratory, lab_id)
        if not lab:
            return None, "المعمل غير موجود"

        if name:
            lab.name = name.strip()
        
        if info is not None:
            lab.info = info.strip() if info else None

        return BaseService.update_commit(lab, success_msg="تم تحديث بيانات المعمل بنجاح", error_prefix="حدث خطأ أثناء التحديث")

    @staticmethod
    def delete_laboratory(lab_id):
        """Delete a laboratory."""
        lab = db.session.get(Laboratory, lab_id)
        if not lab:
            return None, "المعمل غير موجود"

        return BaseService.delete(lab, success_msg="تم حذف المعمل بنجاح", error_prefix="حدث خطأ أثناء الحذف")