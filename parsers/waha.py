import json
import logging
import traceback

from service.message_processor import IncomingMessage

logger = logging.getLogger(__name__)


# استخراج اسم العميل من الـ Payload بأمان تام:
def _extract_sender_name(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    
    # 1. فحص من داخل _data
    raw_data = payload.get("_data", {})
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            raw_data = {}
    elif not isinstance(raw_data, dict):
        raw_data = {}
    name = (
        raw_data.get("notifyName")
        or raw_data.get("pushName")
        or payload.get("notifyName")
        or payload.get("pushName")
        or payload.get("name")
    )
    return str(name).strip() if name else None

# أنواع الرسائل اللي مش هنرد عليها (ريأكشنز، حذف رسالة، إلخ)
IGNORED_MSG_TYPES = {"e2e_notification", "notification_template", "revoked", "reaction"}


def _is_ignored_chat(chat_id: str) -> bool:
    """تجاهل الجروبات، الاستوري/الحالة، النشرات، والبرودكاست"""
    if not chat_id:
        return True
    return (
        "@g.us" in chat_id           # جروب
        or "@newsletter" in chat_id  # قناة/نشرة
        or "@broadcast" in chat_id   # برودكاست
        or "status@broadcast" in chat_id  # ستوري/حالة واتساب
    )


def _is_ad_referral(payload: dict) -> bool:
    """
    تجاهل رسائل الإعلانات (Click-to-WhatsApp Ads).
    غالبًا بتوصل بحقل referral/ctwaContext جوه raw data الرسالة.
    الاسم الدقيق ممكن يختلف حسب الـ engine (WEBJS/NOWEB/GOWS) —
    لو لقيت اسم مختلف في الـ log هنا هو المكان اللي تعدله فيه.
    """
    raw = payload.get("_data", {}) or {}
    return bool(
        raw.get("ctwaContext")
        or raw.get("isAd")
        or (payload.get("referral") or {}).get("source_type") == "ad"
    )


def _debug_print_payload(payload: dict):
    """طباعة الـ Payload بشكل منسق في التيرمنال لتفقد الحقول بدقة"""
    try:
        # عمل نسخة خفيفة لإخفاء الـ Base64 الطويل فقط لتسهيل القراءة
        clean = json.loads(json.dumps(payload, default=str))
        if "media" in clean and isinstance(clean["media"], dict):
            if "data" in clean["media"]:
                clean["media"]["data"] = "<BASE64_IMAGE_DATA_TRUNCATED>"
        if "body" in clean and str(clean["body"]).startswith(("/9j/", "data:image", "JVBERi0")):
            clean["body"] = "<BASE64_BODY_TRUNCATED>"
        print("\n" + "🔍" * 3 + " ================= WAHA INCOMING PAYLOAD =================" + "🔍" * 3)
        print(json.dumps(clean, indent=2, ensure_ascii=False))
        print("=" * 75 + "\n", flush=True)
    except Exception as e:
        print(f"[DEBUG PRINT ERROR] {e}")

def parse_waha_message(payload: dict, page_id, platform_id, platform_name: str = "WhatsApp") -> IncomingMessage | None:
    # 🖨️ طباعة الـ Payload فور وصوله
    _debug_print_payload(payload)
    
    try:
        if not isinstance(payload, dict):
            return None

        # تجاهل الرسائل الصادرة منّا (echo)
        if payload.get("fromMe"):
            return None

        sender_id = payload.get("from")
        if not sender_id:
            logger.warning("WAHA payload received without 'from' field")
            return None

        # تجاهل الجروب / الاستوري / البرودكاست / النشرات
        if _is_ignored_chat(sender_id):
            logger.debug("Ignoring non-personal chat: %s", sender_id)
            return None

        # تجاهل أنواع الأحداث اللي مش رسايل فعلية (ريأكشن، تنبيهات نظام...)
        raw_type = (payload.get("_data", {}) or {}).get("type", "")
        if raw_type in IGNORED_MSG_TYPES:
            logger.debug("Ignoring WAHA event type: %s", raw_type)
            return None

        # تجاهل رسائل الإعلانات (لو مفعّل عندك ctwa ads)
        if _is_ad_referral(payload):
            logger.debug("Ignoring ad-referral message from: %s", sender_id)
            return None

        has_media = payload.get("hasMedia", False)
        media     = payload.get("media")
        msg_body  = payload.get("body")

        # استخراج اسم بروفايل العميل من واتساب
        raw_data = payload.get("_data", {}) or {}
        sender_name = raw_data.get("notifyName") or payload.get("notifyName") or payload.get("pushName")
        sender_name = _extract_sender_name(payload)
        logger.info("[WAHA PARSER] Extracted sender_id=%s | sender_name=%s", sender_id, sender_name)
        # ── ميديا (صور، فيديو، صوت، ملفات) ──────────────────────────────────
        if has_media and media:
            mimetype = media.get("mimetype", "")

            # فحص التعليق المكتوب مع الصورة وتجاهل الـ Base64 الضخم
            caption = payload.get("caption")
            if not caption and msg_body:
                # إذا كان الـ body هو كود Base64 طويل نتجاهله
                if not str(msg_body).startswith(("/9j/", "data:image", "JVBERi0")) and len(str(msg_body)) < 1000:
                    caption = msg_body
                else:
                    caption = "📷 [صورة مرفقة]"
            else:
                caption = caption or "📷 [صورة مرفقة]"

            if "image/webp" in mimetype:
                msg_type = "sticker"
            elif "image/" in mimetype:
                msg_type = "image"
            elif "video/" in mimetype:
                msg_type = "video"
            elif "audio/" in mimetype or "ptt" in raw_type:
                msg_type = "voice"
            elif "application/pdf" in mimetype:
                msg_type = "document"
            else:
                msg_type = "file"

            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type=msg_type,
                text=caption,  # 👈 حفظ التعليق أو "صورة مرفقة" بدلاً من الـ Base64
                media=media,
                sender_name=sender_name, # 👈 إضافة اسم العميل
            )

        # ── نص عادي ──────────────────────────────────────────────────────────
        if msg_body and str(msg_body).strip():
            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type="text",
                text=msg_body,
                sender_name=sender_name,   # 👈 إضافة اسم العميل
            )

        return None

    except Exception:
        logger.critical(
            "Fatal error in parse_waha_message:\n%s\nPayload: %s",
            traceback.format_exc(), payload,
        )
        return None