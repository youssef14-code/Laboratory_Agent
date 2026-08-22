from models.models import Platform, db
from sqlalchemy.orm import joinedload
from software_service.base_service import BaseService


class PlatformService(BaseService):

    @staticmethod
    def create_platform(name):
        if not name or not name.strip():
            return None, "اسم المنصة مطلوب"
        
        name = name.strip().lower()  
        existing_platform = Platform.query.filter_by(name=name).first()
        if existing_platform:
            return None, "يوجد منصة أخرى بنفس هذا الاسم"
            
        new_platform = Platform(name=name)
        return BaseService.commit(new_platform, success_msg="تم إنشاء المنصة بنجاح", error_prefix="حدث خطأ أثناء إنشاء المنصة")
            
    @staticmethod
    def get_all_platforms():
        platforms = Platform.query.options(joinedload(Platform.pages)).all()
        return platforms, "تم العثور على جميع المنصات"

    @staticmethod
    def update_platform(platform_id, name=None):
        platform = db.session.get(Platform, platform_id)

        if not platform:
            return None, "المنصة غير موجودة"

        if name:
            name = name.strip().lower()
            existing_platform = Platform.query.filter_by(name=name).first()
            if existing_platform and existing_platform.id != platform.id:
                return None, "يوجد منصة أخرى بنفس هذا الاسم"
            platform.name = name

        return BaseService.update_commit(platform, success_msg="تم تحديث المنصة بنجاح", error_prefix="حدث خطأ أثناء تحديث المنصة")
        
    @staticmethod
    def get_platform_by_id(platform_id):
        platform = db.session.get(Platform, platform_id)
        if not platform:
            return None, "المنصة غير موجودة"
        return platform, "تم العثور على المنصة"
    