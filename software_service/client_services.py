"""
software_services/client_services.py
"""

from xmlrpc import client

from models.models import Client, db, Page, Laboratory
from software_service.base_service import BaseService


class ClientService(BaseService):

    # ── read ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_clients_for_page(platform_id, page_id, search=None, page_num=1, per_page=10):
        query = Client.query.filter_by(platform_id=platform_id, page_id=page_id)

        if search:
            query = query.filter(Client.sender_id.ilike(f'%{search}%'))

        query = query.order_by(Client.expiration_date.desc())
        return BaseService.paginate(query, page=page_num, per_page=per_page, success_msg="تم العثور على العملاء")

    @staticmethod
    def get_client(platform_id, page_id, sender_id):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()
        if not client:
            return None, "العميل غير موجود"
        return client, "تم العثور على العميل"

    # ── write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def update_client_summary(platform_id, page_id, sender_id, summary):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()
        if not client:
            return None, "العميل غير موجود"

        client.summary = summary
        return BaseService.update_commit(client, success_msg="تم تحديث ملخص العميل بنجاح", error_prefix="حدث خطأ أثناء التحديث")

    @staticmethod
    def update_client_summary_and_last_bot_message(sender_id, page_id, platform_id, summary=None, last_bot_message=None):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()

        is_new = False
        if not client:
            client = Client(
                platform_id=platform_id,
                page_id=page_id,
                sender_id=sender_id,
                summary=summary,
                last_bot_message=last_bot_message
            )
            is_new = True
        else:
            if summary is not None:
                client.summary = summary
            if last_bot_message is not None:
                client.last_bot_message = last_bot_message

        if is_new:
            return BaseService.commit(client, success_msg="تم حفظ حالة العميل بنجاح", error_prefix="حدث خطأ أثناء حفظ حالة العميل")
        else:
            return BaseService.update_commit(client, success_msg="تم حفظ حالة العميل بنجاح", error_prefix="حدث خطأ أثناء حفظ حالة العميل")

    @staticmethod
    def delete_client(platform_id, page_id, sender_id):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()
        if not client:
            return None, "العميل غير موجود"
        return BaseService.delete(client, success_msg="تم حذف العميل بنجاح", error_prefix="حدث خطأ أثناء الحذف")

    @staticmethod
    def get_or_create_client(sender_id, page_id, platform_id):
        p_id = int(platform_id) if platform_id is not None else 1
        pg_id = str(page_id) if page_id is not None else "default"
        s_id = str(sender_id) if sender_id is not None else "unknown"

        page = Page.query.filter_by(platform_id=p_id, page_id=pg_id).first()
        if not page:
            lab = Laboratory.query.first()
            if not lab:
                lab = Laboratory(id=1, name="Default Lab", address="Default Address", info="Default Info")
                lab, msg = BaseService.commit(lab, success_msg="Lab created", error_prefix="Lab error")
                if not lab:
                    return None, msg

            page = Page(platform_id=p_id, page_id=pg_id, laboratory_id=lab.id, token="default_token")
            page, msg = BaseService.commit(page, success_msg="Page created", error_prefix="Page error")
            if not page:
                return None, msg

        client = Client.query.filter_by(platform_id=p_id, page_id=pg_id, sender_id=s_id).first()
        if not client:
            client = Client(platform_id=p_id, page_id=pg_id, sender_id=s_id, summary="", last_bot_message="")
            client, msg = BaseService.commit(client, success_msg="تم إنشاء العميل بنجاح", error_prefix="حدث خطأ أثناء إنشاء العميل")
            if not client:
                return None, msg
            return client, msg

        return client, "تم العثور على العميل"

