from models.models import User, db
from software_service.base_service import BaseService


class UserService(BaseService):


    
    @staticmethod
    def create_user(name, password):
        name = name.strip().lower()
        existing_user = User.query.filter_by(username=name).first()
        if existing_user:
            return None, "اسم المستخدم موجود بالفعل"

        new_user = User(username=name, password=password)
        return BaseService.commit(new_user, success_msg="تم إنشاء المستخدم بنجاح", error_prefix="حدث خطأ أثناء إنشاء المستخدم")

    
    @staticmethod
    def update_user(user_id, name=None, password=None):
        user = db.session.get(User, user_id)

        if not user:
            return None, "المستخدم غير موجود"

        if name and name != user.username:
            the_user = User.query.filter_by(username=name).first()

            if the_user:
                return None, "اسم المستخدم موجود بالفعل"

            user.username = name

        if password:
            user.password = password

        return BaseService.update_commit(user, success_msg="تم تحديث المستخدم بنجاح", error_prefix="حدث خطأ أثناء تحديث المستخدم")

    
    @staticmethod
    def login_user(name, password):
        user = User.query.filter_by(username=name).first()

        if user and user.password == password:
            return user, "تم تسجيل الدخول بنجاح"
        else:
            return None, "اسم المستخدم أو كلمة المرور غير صحيحة"

    
    @staticmethod
    def get_user_by_id(user_id):
        user = db.session.get(User, user_id)

        if user:
            return user, "تم العثور على المستخدم"
        else:
            return None, "المستخدم غير موجود"

    
    @staticmethod
    def get_all_users():
        return User.query.all()
