import io
import json
import logging
import os
from time import time
import requests

from platforms.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class FacebookHandler(BaseHandler):
    platform_id = 1
    API_VERSION = "v19.0"

    def __init__(self, page):
        super().__init__(page)
        self.base_url = f"https://graph.facebook.com/{self.API_VERSION}"
        self.params   = {"access_token": self.token}

    @property
    def platform_name(self) -> str:
        try:
            return self.page.platform.name
        except AttributeError:
            return "Facebook"

    # ── text ─────────────────────────────────────────────────────────────────

    MAX_FB_TEXT_LEN = 2000

    def _split_text(self, text: str, max_len: int = None):
        """يقسم النص لأجزاء كل جزء أقل من أو يساوي الحد الأقصى، من غير ما يقطع كلمة نص نص."""
        max_len = max_len or self.MAX_FB_TEXT_LEN
        text = text.strip()
        if len(text) <= max_len:
            return [text]

        parts = []
        while len(text) > max_len:
            split_at = text.rfind("\n\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1:
                split_at = max_len
            parts.append(text[:split_at].strip())
            text = text[split_at:].strip()
        if text:
            parts.append(text)
        return parts

    def send(self, recipient_id: str, text: str):
        if not text or not text.strip():
            return None

        chunks = self._split_text(text)
        last_response = None

        for i, chunk in enumerate(chunks):
            logger.debug("[FB SEND] to=%s part=%d/%d", recipient_id, i + 1, len(chunks))
            payload = {
                "messaging_type": "RESPONSE",
                "recipient": {"id": recipient_id},
                "message":   {"text": chunk},
            }
            last_response = self._post_json(f"{self.base_url}/me/messages", payload)

        return last_response

    # ── file (PDF ticket) ─────────────────────────────────────────────────────

    def send_image(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str = "booking_ticket.png",
        mime_type: str = "image/png",
    ):
        print(f"[FB SEND IMAGE] Sending image to={recipient_id} | size={len(file_bytes)} bytes")

        recipient_json = json.dumps({"id": str(recipient_id)})
        message_json = json.dumps({
            "attachment": {
                "type": "image",
                "payload": {}
            }
        })

        # نتأكد أن الملف bytes جاهز للإرسال
        raw_data = file_bytes.getvalue() if hasattr(file_bytes, "getvalue") else file_bytes

        # 🔄 محاولة الإرسال مع Retry (3 محاولات) في حال تقلب الإنترنت
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/me/messages",
                    params=self.params,
                    data={
                        "recipient": recipient_json,
                        "message": message_json,
                    },
                    files={
                        "filedata": (filename, raw_data, mime_type),
                    },
                    timeout=(15, 60),  # 15s للاتصال و 60s لرفع الصورة
                )

                print(f"[FB SEND IMAGE RESPONSE] attempt={attempt} | status={response.status_code} | body={response.text}")

                if response.status_code in [200, 201]:
                    logger.info("[FB] ✅ Image sent successfully to recipient=%s", recipient_id)
                    return response
                else:
                    logger.error("[FB IMAGE ERROR] status=%s body=%s", response.status_code, response.text)

            except Exception as e:
                print(f"[FB IMAGE ERROR] Attempt {attempt}/{max_retries} failed: {e}")
                logger.error("[FB IMAGE ERROR] Attempt %s/%s failed: %s", attempt, max_retries, e)
                if attempt == max_retries:
                    return None
                time.sleep(1)  # انتظار ثانية قبل المحاولة التالية

        return None
    # ── typing indicator ─────────────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        """إرسال إشارة 'تمت القراءة' و 'جاري الكتابة...' للمستخدم."""
        # قراءة التوكن من الـ .env مباشرة أو من كائن الصفحة
        token = os.environ.get("FB_PAGE_ACCESS_TOKEN") or os.environ.get("PAGE_ACCESS_TOKEN") or getattr(self, "access_token", None)
        if not token:
            return
        url = "https://graph.facebook.com/v19.0/me/messages"
        params = {"access_token": token}
        # 1. إرسال mark_seen
        try:
            requests.post(
                url,
                params=params,
                json={"recipient": {"id": recipient_id}, "sender_action": "mark_seen"},
                timeout=3,
            )
        except Exception:
            pass
        # 2. إرسال typing_on
        try:
            requests.post(
                url,
                params=params,
                json={"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
                timeout=3,
            )
        except Exception:
            pass

    # ── comments handling (Like + Public Reply + Private Reply) ─────────────

    def like_comment(self, comment_id: str):
        """1. عمل Like على كومنت العميل من الصفحة."""
        logger.debug("[FB LIKE COMMENT] comment_id=%s", comment_id)
        url = f"{self.base_url}/{comment_id}/likes"
        try:
            return requests.post(url, params=self.params, timeout=10)
        except Exception as e:
            logger.error("[FB LIKE COMMENT ERROR] %s", e)
            return None

    def reply_to_comment(
        self,
        comment_id: str,
        static_message: str = "تم الرد في الخاص يا فندم 🙏",
    ):
        """2. رد عام تحت الكومنت."""
        logger.debug("[FB PUBLIC COMMENT REPLY] comment_id=%s", comment_id)
        payload = {"message": static_message}
        return self._post_json(f"{self.base_url}/{comment_id}/comments", payload)

    def send_private_reply(
        self,
        page_id: str,
        page_access_token: str,
        comment_id: str,
        text: str = "أهلاً بحضرتك في معامل د/ ماجد صفوت شاكر! حابب نساعد حضرتك إزاي اليوم؟",
    ):
        """3. إرسال رسالة خاصة على ماسنجر للشخص صاحب الكومنت."""
        logger.debug("[FB PRIVATE REPLY] comment_id=%s page_id=%s", comment_id, page_id)

        url = f"{self.base_url}/{page_id}/messages"
        params = {"access_token": page_access_token}
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        }

        try:
            response = requests.post(url, params=params, json=payload, timeout=10)
            if response.status_code not in [200, 201]:
                logger.error("[FB PRIVATE REPLY ERROR] status=%s body=%s", response.status_code, response.text)
            return response
        except Exception as e:
            logger.error("[FB PRIVATE REPLY ERROR] %s", e)
            return None

    def handle_comment(
        self,
        comment_id: str,
        public_msg: str = "تم الرد في الخاص يا فندم 🙏",
        private_msg: str = "أهلاً بحضرتك في معامل د/ ماجد صفوت شاكر! حابب نساعد حضرتك إزاي اليوم؟",
    ):
        """معالجة الكومنت الجديد بتنفيذ الـ 3 خطوات معاً."""
        print(f"\n💬 [FB COMMENT] New Comment detected: id={comment_id}")

        # 1. لايك
        self.like_comment(comment_id)

        # 2. رد عام تحت الكومنت
        if public_msg:
            self.reply_to_comment(comment_id, static_message=public_msg)

        # 3. رسالة خاصة على الماسنجر
        if private_msg:
            self.send_private_reply(
                page_id=self.page_id,
                page_access_token=self.token,
                comment_id=comment_id,
                text=private_msg,
            )
        print(f"✅ [FB COMMENT] Like + Public Reply + Private Message sent successfully!\n")
    # ── helpers ───────────────────────────────────────────────────────────────

    def _post_json(self, url: str, payload: dict):
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                params=self.params,
                timeout=10,
            )
            if response.status_code not in [200, 201]:
                logger.error(
                    "[FB ERROR] status=%s body=%s",
                    response.status_code, response.text,
                )
            return response
        except Exception as e:
            logger.error("[FB ERROR] Connection failed: %s", e)
            return None

    def parse_message(self, payload, page_id):
        from parsers.facebook import parse_facebook_message
        return parse_facebook_message(
            payload,
            page_id,
            platform_id=self.platform_id,
            platform_name=self.platform_name,
        )
        # ── media download (prescription image) ──────────────────────────────────

    def download_media(self, media: dict, media_type: str = "media") -> bytes | None:
        """
        صور الماسنجر بتيجي كـ URL في الـ attachment payload، والرابط ده
        عادةً CDN link موقّع من فيسبوك (مش محتاج access_token للتحميل).
        """
        image_url = media.get("url") if media else None
        if not image_url:
            logger.warning("[FacebookHandler] download_media: no url in media=%s", media)
            return None
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception:
            logger.exception("[FacebookHandler] download_media failed | url=%s", image_url)
            return None    