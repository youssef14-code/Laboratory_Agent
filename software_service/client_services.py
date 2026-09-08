"""
software_services/client_services.py
"""

import logging


from models.models import ChatHistory, Client, db, Page, Laboratory
from notified_center.EmailSender import send_production_alert
from software_service.base_service import BaseService

logger = logging.getLogger(__name__)
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
    def get_or_create_client(
        sender_id,
        page_id,
        platform_id,
        lock=False
    ):
        p_id = int(platform_id) if platform_id is not None else 1
        pg_id = str(page_id) if page_id is not None else "default"
        s_id = str(sender_id) if sender_id is not None else "unknown"

        page = Page.query.filter_by(
            platform_id=p_id,
            page_id=pg_id
        ).first()

        if not page:
            lab = Laboratory.query.first()

            if not lab:
                lab = Laboratory(
                    id=1,
                    name="Default Lab",
                    info="Default Info",
             )

                lab, message = BaseService.commit(
                    lab,
                    success_msg="Lab created",
                    error_prefix="Lab error",
                )

                if not lab:
                    return None, message

            page = Page(
                platform_id=p_id,
                page_id=pg_id,
                laboratory_id=lab.id,
                token="default_token",
            )

            page, message = BaseService.commit(
                page,
                success_msg="Page created",
                error_prefix="Page error",
            )

            if not page:
                return None, message

        client_query = Client.query.filter_by(
            platform_id=p_id,
            page_id=pg_id,
            sender_id=s_id
        )

        if lock:
            client_query = client_query.with_for_update()

        client = client_query.first()

        if client:
            return client, "تم العثور على العميل"

        client = Client(
            platform_id=p_id,
            page_id=pg_id,
            sender_id=s_id,
            summary="",
            last_bot_message="",
        )

        client, message = BaseService.commit(
            client,
            success_msg="تم إنشاء العميل بنجاح",
            error_prefix="حدث خطأ أثناء إنشاء العميل",
        )

        if not client:
            return None, message

        return client, message



    @staticmethod
    def get_chat_history(platform_id, page_id, sender_id, limit=ChatHistory.MAX_HISTORY):
        """Return the latest exchanges ordered from oldest to newest."""
        try:
            safe_limit = max(1, int(limit))
            rows = (
                ChatHistory.query
                .filter_by(
                    platform_id=platform_id,
                    page_id=page_id,
                    sender_id=sender_id,
                )
                .order_by(ChatHistory.id.desc())
                .limit(safe_limit)
                .all()
            )
            return list(reversed(rows)), "تم جلب سجل المحادثة بنجاح"

        except Exception as error:
            logger.exception(
                "[ClientService.get_chat_history] Error: %s",
                error,
            )
            try:
                send_production_alert(
                    subject="ClientService get_chat_history Exception",
                    body_or_error=error,
                    context={
                        "platform_id": platform_id,
                        "page_id": page_id,
                        "sender_id": sender_id,
                    },
                )
            except Exception:
                logger.exception("Failed to send get_chat_history alert")

            return [], f"حدث خطأ أثناء جلب سجل المحادثة: {error}"

    @staticmethod
    def format_chat_history(history):
        """Convert ChatHistory rows into chronological prompt context."""
        if not history:
            return "(لا يوجد سجل محادثة سابق)"

        lines = []
        for exchange in history:
            date_str = ""
            if exchange.created_at:
                date_str = exchange.created_at.strftime("%Y-%m-%d %H:%M")

            lines.append(f"--- [{date_str}] ---" if date_str else "---")
            lines.append(f"User: {exchange.user_message}")
            lines.append(f"Bot: {exchange.bot_reply}")

        return "\n".join(lines)

    @staticmethod
    def save_chat_exchange(
        platform_id,
        page_id,
        sender_id,
        user_message,
        bot_reply,
        max_history=ChatHistory.MAX_HISTORY,
        summary=None,
    ):
        """
        Save one user/bot exchange, trim older exchanges, and update Client.

        All changes are committed together in a single transaction.
        """
        try:
            safe_max_history = max(1, int(max_history))
            clean_user_message = (
                str(user_message or "").strip()
                or "[رسالة بدون نص أو تحتوي على مرفق]"
            )
            clean_bot_reply = str(bot_reply or "").strip()
            clean_summary = str(summary or "").strip()

            client, client_message = ClientService.get_or_create_client(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                lock=True,
            )
            if client is None:
                raise RuntimeError(client_message)

            entry = ChatHistory(
                platform_id=client.platform_id,
                page_id=client.page_id,
                sender_id=client.sender_id,
                user_message=clean_user_message,
                bot_reply=clean_bot_reply,
            )
            db.session.add(entry)
            db.session.flush()

            # Query only the exchanges that fall outside the retained window.
            ids_to_delete = [
                row[0]
                for row in (
                    db.session.query(ChatHistory.id)
                    .filter_by(
                        platform_id=client.platform_id,
                        page_id=client.page_id,
                        sender_id=client.sender_id,
                    )
                    .order_by(ChatHistory.id.desc())
                    .offset(safe_max_history)
                    .all()
                )
            ]

            if ids_to_delete:
                (
                    db.session.query(ChatHistory)
                    .filter(ChatHistory.id.in_(ids_to_delete))
                    .delete(synchronize_session=False)
                )

            if clean_summary:
                client.summary = clean_summary

            client.last_bot_message = clean_bot_reply
            db.session.commit()

            return client, "تم حفظ التبادل الحواري وتحديث حالة العميل بنجاح"

        except Exception as error:
            db.session.rollback()
            logger.exception(
                "[ClientService.save_chat_exchange] Error: %s",
                error,
            )
            try:
                send_production_alert(
                    subject="ClientService save_chat_exchange Exception",
                    body_or_error=error,
                    context={
                        "platform_id": platform_id,
                        "page_id": page_id,
                        "sender_id": sender_id,
                    },
                )
            except Exception:
                logger.exception("Failed to send save_chat_exchange alert")

            return None, f"حدث خطأ أثناء حفظ سجل المحادثة: {error}"

