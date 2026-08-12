from models.models import Platform, db
from sqlalchemy.orm import joinedload

class PlatformService:

    @staticmethod
    def create_platform(name):
        
        name=name.strip().lower()  
        exiting_platform = Platform.query.filter_by(name=name).first()
        if exiting_platform:
            return None, "يوجد منصة أخرى بنفس هذا الاسم"
            
        try:
            
            new_platform = Platform(
                name=name
            )

            db.session.add(new_platform)
            db.session.commit()
            return new_platform, "تم إنشاء المنصة بنجاح"
        except Exception as e:
            db.session.rollback() 
            return None, f"حدث خطأ أثناء إنشاء المنصة: {str(e)}"
            
    @staticmethod
    def get_all_platforms():
        platforms = Platform.query.options(joinedload(Platform.pages)).all()
        return platforms, "تم العثور على جميع المنصات"

    @staticmethod
    def update_platform(platform_id, name=None):
        platform = Platform.query.get(platform_id)

        if not platform:
            return None, "المنصة غير موجودة"

        if name:
            name=name.strip().lower()
            existing_platform = Platform.query.filter_by(name=name).first()
            if existing_platform and existing_platform.id != platform.id:
                return None, "يوجد منصة أخرى بنفس هذا الاسم"
            platform.name = name

        try:
            db.session.commit()
            return platform, "تم تحديث المنصة بنجاح"
        except Exception as e:
            db.session.rollback() 
            return None, f"حدث خطأ أثناء تحديث المنصة: {str(e)}"
        
    @staticmethod
    def get_platform_by_id(platform_id):
        platform = Platform.query.get(platform_id)
        if not platform:
          return None, "المنصة غير موجودة"
        return platform, "تم العثور على المنصة"    