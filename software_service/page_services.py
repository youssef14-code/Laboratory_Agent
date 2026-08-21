import token

from models.models import Page, Client, Platform, db
from sqlalchemy.orm import joinedload
from software_service.base_service import BaseService
from software_service.platform_services import PlatformService
from software_service.client_services import ClientService


class PageService(BaseService):

    # ── Pages ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_pages():
        pages = Page.query.options(joinedload(Page.platform), joinedload(Page.clients)).all()
        return pages, "تم العثور على الصفحات"

    @staticmethod
    def get_page(platform_id, page_id):
        page = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if not page:
            return None, "الصفحة غير موجودة"
        return page, "تم العثور على الصفحة"

    @staticmethod
    def create_page(laboratory_id, platform_id, page_id, token):
        if not page_id or not page_id.strip():
            return None, "معرّف الصفحة مطلوب"
        if not token or not token.strip():
            return None, "الرمز (Token) مطلوب"
        if not laboratory_id:
            return None, "المعمل مطلوب"
        if not platform_id:
            return None, "المنصة مطلوبة"   
           
        page_id = page_id.strip()
        existing = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if existing:
            return None, "هذه الصفحة مضافة بالفعل لهذه المنصة"

        new_page = Page(
            laboratory_id=laboratory_id,
            platform_id=platform_id,
            page_id=page_id,
            token=token.strip(),
        )
        return BaseService.commit(new_page, success_msg="تم إضافة الصفحة بنجاح", error_prefix="حدث خطأ أثناء إضافة الصفحة")

    @staticmethod
    def update_page_token(platform_id, page_id, token):
        if not token or not token.strip():
            return None, "الرمز (Token) مطلوب"
        
        page = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if not page:
            return None, "الصفحة غير موجودة"

        page.token = token.strip()
        return BaseService.update_commit(page, success_msg="تم تحديث الرمز بنجاح", error_prefix="حدث خطأ أثناء التحديث")

    @staticmethod
    def delete_page(platform_id, page_id):
        page = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if not page:
            return None, "الصفحة غير موجودة"

        return BaseService.delete(page, success_msg="تم حذف الصفحة بنجاح", error_prefix="حدث خطأ أثناء الحذف")

    # ── Platforms (for the dropdown when adding a page) ────────────────────

    @staticmethod
    def get_all_platforms():
        return PlatformService.get_all_platforms()

    # ── Clients (scoped to one page) ────────────────────────────────────────

    @staticmethod
    def get_clients_for_page(platform_id, page_id, search=None, page_num=1, per_page=10):
        return ClientService.get_clients_for_page(platform_id, page_id, search, page_num, per_page)

    @staticmethod
    def get_client(platform_id, page_id, sender_id):
        return ClientService.get_client(platform_id, page_id, sender_id)

    @staticmethod
    def update_client_summary(platform_id, page_id, sender_id, summary):
        return ClientService.update_client_summary(platform_id, page_id, sender_id, summary)

    @staticmethod
    def delete_client(platform_id, page_id, sender_id):
        return ClientService.delete_client(platform_id, page_id, sender_id)
