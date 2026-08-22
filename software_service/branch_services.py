from models.models import Branch, db
from software_service.base_service import BaseService

class BranchService(BaseService):

    @staticmethod
    def get_branches_by_laboratory(lab_id, page=1, per_page=10):
        """Get paginated branches for a specific laboratory."""
        query = Branch.query.filter_by(laboratory_id=lab_id).order_by(Branch.id.desc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم جلب الفروع بنجاح")

    @staticmethod
    def get_branch_by_id(branch_id):
        branch = db.session.get(Branch, branch_id)
        if not branch:
            return None, "الفرع غير موجود"
        return branch, "تم العثور على الفرع"

    @staticmethod
    def create_branch(laboratory_id, address, phone=None, working_hours=None):
        if not address or not address.strip():
            return None, "عنوان الفرع مطلوب"

        branch = Branch(
            laboratory_id=laboratory_id,
            address=address.strip(),
            phone=phone.strip() if phone else None,
            working_hours=working_hours.strip() if working_hours else None
        )
        return BaseService.commit(branch, success_msg="تم إضافة الفرع بنجاح", error_prefix="حدث خطأ أثناء إضافة الفرع")

    @staticmethod
    def update_branch(branch_id, address=None, phone=None, working_hours=None):
        branch = db.session.get(Branch, branch_id)
        if not branch:
            return None, "الفرع غير موجود"

        if address:
            branch.address = address.strip()
        if phone is not None:
            branch.phone = phone.strip() if phone else None
        if working_hours is not None:
            branch.working_hours = working_hours.strip() if working_hours else None

        return BaseService.update_commit(branch, success_msg="تم تحديث الفرع بنجاح", error_prefix="حدث خطأ أثناء التحديث")

    @staticmethod
    def delete_branch(branch_id):
        branch = db.session.get(Branch, branch_id)
        if not branch:
            return None, "الفرع غير موجود"
        return BaseService.delete(branch, success_msg="تم حذف الفرع بنجاح", error_prefix="حدث خطأ أثناء الحذف")