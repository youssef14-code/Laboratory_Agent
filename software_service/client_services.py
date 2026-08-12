"""
software_services/client_services.py
"""

from models.models import Client, db, Page, Laboratory


class ClientService:

    # ── read ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_clients_for_page(platform_id, page_id, search=None, page_num=1, per_page=10):
        query = Client.query.filter_by(platform_id=platform_id, page_id=page_id)

        if search:
            query = query.filter(Client.sender_id.ilike(f'%{search}%'))

        query = query.order_by(Client.expiration_date.desc())
        pagination = query.paginate(page=page_num, per_page=per_page, error_out=False)
        return pagination, "تم العثور على العملاء"

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
        try:
            client.summary = summary
            db.session.commit()
            return client, "تم تحديث ملخص العميل بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء التحديث: {str(e)}"

    @staticmethod
    def update_client_summary_and_last_bot_message(sender_id, page_id, platform_id, summary=None, last_bot_message=None):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()

        if not client:
            client = Client(
                platform_id=platform_id,
                page_id=page_id,
                sender_id=sender_id,
                summary=summary,
                last_bot_message=last_bot_message
            )
            db.session.add(client)
        else:
            if summary is not None:
                client.summary = summary
            if last_bot_message is not None:
                client.last_bot_message = last_bot_message

        try:
            db.session.commit()
            return client, "تم حفظ حالة العميل بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء حفظ حالة العميل: {str(e)}"

    @staticmethod
    def delete_client(platform_id, page_id, sender_id):
        client = Client.query.filter_by(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        ).first()
        if not client:
            return None, "العميل غير موجود"
        try:
            db.session.delete(client)
            db.session.commit()
            return client, "تم حذف العميل بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء الحذف: {str(e)}"

    @staticmethod
    def get_or_create_client(sender_id, page_id, platform_id):
        
        
        
        p_id = int(platform_id) if platform_id is not None else 1
        pg_id = str(page_id) if page_id is not None else "default"
        s_id = str(sender_id) if sender_id is not None else "unknown"

        # Ensure Page exists to prevent ForeignKeyConstraint error
        page = Page.query.filter_by(platform_id=p_id, page_id=pg_id).first()
        if not page:
            lab = Laboratory.query.first()
            if not lab:
                lab = Laboratory(id=1, name="Default Lab", address="Default Address", info="Default Info")
                db.session.add(lab)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    lab = Laboratory.query.first()

            lab_id = lab.id if lab else 1
            page = Page(platform_id=p_id, page_id=pg_id, laboratory_id=lab_id, token="default_token")
            db.session.add(page)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[ClientService] Auto-created page error: {e}")

        client = Client.query.filter_by(
            platform_id=p_id, page_id=pg_id, sender_id=s_id
        ).first()
        if not client:
            client = Client(
                platform_id=p_id,
                page_id=pg_id,
                sender_id=s_id,
                summary="",
                last_bot_message=""
            )
            db.session.add(client)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[ClientService] Error creating client: {e}")
        return client
