from models.models import User, db
from software_service.base_service import BaseService


class UserService(BaseService):

    @staticmethod
    def create_user(name, password, role="user"):
        name = name.strip().lower()
        existing_user = User.query.filter_by(username=name).first()
        if existing_user:
            return None, "اسم المستخدم موجود بالفعل"

        if role not in ["admin", "user"]:
            role = "user"

        new_user = User(username=name, password=password, role=role)
        return BaseService.commit(new_user, success_msg="تم إنشاء المستخدم بنجاح", error_prefix="حدث خطأ أثناء إنشاء المستخدم")

    @staticmethod
    def update_user(user_id, name=None, password=None, role=None):
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

        if role and role in ["admin", "user"]:
            user.role = role

        return BaseService.update_commit(user, success_msg="تم تحديث المستخدم بنجاح", error_prefix="حدث خطأ أثناء تحديث المستخدم")

    @staticmethod
    def get_user_by_id(user_id):
        user = db.session.get(User, user_id)
        if user:
            return user, "تم العثور على المستخدم"
        return None, "المستخدم غير موجود"

    @staticmethod
    def get_all_users():
        return User.query.all()