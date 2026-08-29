import logging
import traceback

from service.message_processor import IncomingMessage

logger = logging.getLogger(__name__)


def parse_facebook_message(
    messaging,
    page_id,
    platform_id,
    platform_name: str = "Facebook",
) -> IncomingMessage | None:

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

        # Text message
        text = msg.get("text")

        if text:
            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type="text",
                text=text,
            )

        # Attachments
        attachments = msg.get("attachments")

        if attachments:
            attachment = attachments[0]

            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type=attachment.get("type", "media"),
                media=attachment.get("payload"),
            )

        return None

    except Exception:
        logger.critical(
            "Fatal error in parse_facebook_message:\n"
            f"{traceback.format_exc()}"
        )
        return None


def parse_facebook_comment(change: dict) -> str | None:
    try:
        # must be a feed change
        if change.get("field") != "feed":
            return None

        value = change.get("value", {})

        # must be a new comment (not edit/delete/like/...)
        if value.get("item") != "comment" or value.get("verb") != "add":
            return None

        # ignore replies to other comments (has parent_id != post_id)
        if value.get("parent_id") and value.get("parent_id") != value.get("post_id"):
            return None

        comment_id = value.get("comment_id")
        if not comment_id:
            return None
        if "_" in comment_id:  # Facebook sometimes sends comment_id as "postid_commentid"
            comment_id = comment_id.split("_")[1]

        return comment_id

    except Exception:
        logger.critical(
            "Fatal error in parse_facebook_comment:\n"
            f"{traceback.format_exc()}"
        )
        return None