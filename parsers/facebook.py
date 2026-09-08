import logging
import traceback

from service.message_processor import IncomingMessage

logger = logging.getLogger(__name__)


def parse_facebook_message(
    messaging,
    page_id,
    platform_id,
    platform_name: str = "Facebook",
) -> list[IncomingMessage] | None:

    try:
        # Ignore delivery events
        if "delivery" in messaging:
            return None

        # Ignore read events
        if "read" in messaging:
            return None

        # Ignore non-message events
        if "message" not in messaging:
            return None

        msg = messaging["message"]

        # Ignore bot echo messages
        if msg.get("is_echo", False):
            return None

        # Sender
        sender_id = messaging.get("sender", {}).get("id")
        if not sender_id:
            return None

        text = msg.get("text")
        attachments = msg.get("attachments")
        
        # 🖼️ 1. إذا كان هناك مرفقات (صور متعددة)
        if attachments:
            parsed_list = []
            for att in attachments:
                att_type = att.get("type", "image")
                parsed_list.append(
                    IncomingMessage(
                        sender_id=sender_id,
                        page_id=page_id,
                        platform_id=platform_id,
                        platform_name=platform_name,
                        msg_type=att_type,
                        text=text,
                        media=att.get("payload"),
                    )
                )
            return parsed_list

        # 📝 2. إذا كانت رسالة نصية فقط بدون مرفقات
        if text:
            return [
                IncomingMessage(
                    sender_id=sender_id,
                    page_id=page_id,
                    platform_id=platform_id,
                    platform_name=platform_name,
                    msg_type="text",
                    text=text,
                )
            ]

        return None

    except Exception:
        logger.critical(
            "Fatal error in parse_facebook_message:\n"
            f"{traceback.format_exc()}"
        )
        return None 


def parse_facebook_comment(change: dict, page_id: str = None) -> str | None:
    try:
        # must be a feed change
        if change.get("field") != "feed":
            return None

        value = change.get("value", {})

        # must be a new comment (not edit/delete/like/...)
        if value.get("item") != "comment" or value.get("verb") != "add":
            return None

        # 🛡️ تجاهل الكومنتات الصادرة من الصفحة نفسها لمنع الـ Infinite Loop
        from_id = str(value.get("from", {}).get("id", ""))
        if page_id and from_id == str(page_id):
            logger.debug("[FB COMMENT] Ignoring comment from page itself (loop prevention)")
            return None

        # ignore replies to other comments (has parent_id != post_id)
        if value.get("parent_id") and value.get("parent_id") != value.get("post_id"):
            return None

        # إبقاء الـ comment_id كاملاً كما يرسله فيسبوك (مطلوب لـ Like و Private Reply)
        comment_id = value.get("comment_id")
        if not comment_id:
            return None

        return str(comment_id)

    except Exception:
        logger.exception("Error parsing Facebook comment")
        return None