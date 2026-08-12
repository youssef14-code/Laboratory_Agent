from models.models import Page, Client, Platform, db
from sqlalchemy.orm import joinedload
from software_service.platform_services import PlatformService
from software_service.client_services import ClientService


class PageService:

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
        page_id = page_id.strip()
        existing = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if existing:
            return None, "هذه الصفحة مضافة بالفعل لهذه المنصة"

        try:
            new_page = Page(
                laboratory_id=laboratory_id,
                platform_id=platform_id,
                page_id=page_id,
                token=token.strip(),
            )
            db.session.add(new_page)
            db.session.commit()
            return new_page, "تم إضافة الصفحة بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء إضافة الصفحة: {str(e)}"

    @staticmethod
    def update_page_token(platform_id, page_id, token):
        page = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if not page:
            return None, "الصفحة غير موجودة"
        try:
            page.token = token.strip()
            db.session.commit()
            return page, "تم تحديث الرمز بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء التحديث: {str(e)}"

    @staticmethod
    def delete_page(platform_id, page_id):
        page = Page.query.filter_by(platform_id=platform_id, page_id=page_id).first()
        if not page:
            return None, "الصفحة غير موجودة"
        try:
            db.session.delete(page)
            db.session.commit()
            return page, "تم حذف الصفحة بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء الحذف: {str(e)}"

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