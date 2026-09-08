import base64
import logging
import os
import requests

from platforms.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class WahaHandler(BaseHandler):
    platform_id = 2
    MAX_WAHA_TEXT_LEN = 4000

    def __init__(self, page):
        super().__init__(page)
        self.base_url = self._resolve_base_url(getattr(page, "page_id", None))
        # جعل الـ session ديناميكية حسب الـ page_id لتشغيل عدة أرقام/جلسات
        self.session = getattr(page, "page_id", None) or "default"
        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": os.environ.get("WAHA_API_KEY", ""),
        }

    @staticmethod
    def _resolve_base_url(page_id):
        """Pick the right WAHA container for this page, via env-var mapping."""
        instances = [
            (os.environ.get("WAHA1_PAGE_ID"), os.environ.get("WAHA1_BASE_URL")),
            (os.environ.get("WAHA2_PAGE_ID"), os.environ.get("WAHA2_BASE_URL")),
            (os.environ.get("WAHA3_PAGE_ID"), os.environ.get("WAHA3_BASE_URL")),
            (os.environ.get("WAHA4_PAGE_ID"), os.environ.get("WAHA4_BASE_URL")),
            (os.environ.get("WAHA5_PAGE_ID"), os.environ.get("WAHA5_BASE_URL")),
        ]

        for mapped_page_id, base_url in instances:
            if page_id and mapped_page_id and page_id == mapped_page_id and base_url:
                return base_url.rstrip("/")

        logger.warning(
            "[WAHA] No instance mapping for page_id=%s, falling back to WAHA_API_URL",
            page_id,
        )

        return os.environ.get(
            "WAHA_API_URL",
            "http://waha:3000"
        ).rstrip("/")

    @property
    def platform_name(self) -> str:
        try:
            return self.page.platform.name
        except AttributeError:
            return "WhatsApp"

    # ── text ─────────────────────────────────────────────────────────────────

    def _split_text(self, text: str, max_len: int = None):
        """يقسم النص لأجزاء كل جزء أقل من أو يساوي الحد الأقصى، بدون قطع الكلمات."""
        max_len = max_len or self.MAX_WAHA_TEXT_LEN
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
            logger.debug("[WAHA SEND] session=%s to=%s part=%d/%d", self.session, recipient_id, i + 1, len(chunks))
            payload = {
                "session": self.session,
                "chatId": recipient_id,
                "text": str(chunk),
            }
            last_response = self._post_json(f"{self.base_url}/api/sendText", payload)

        return last_response

    # ── image (booking ticket, or any photo) ────────────────────────────────

    def send_image(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str = "ticket.png",
        mime_type: str = "image/png",
    ):
        raw_data = file_bytes.getvalue() if hasattr(file_bytes, "getvalue") else file_bytes
        encoded_data = base64.b64encode(raw_data).decode("utf-8")

        payload = {
            "session": self.session,
            "chatId": recipient_id,
            "file": {
                "mimetype": mime_type,
                "filename": filename,
                "data": encoded_data,
            },
        }

        # 🔄 محاولة الإرسال مع Retry (3 محاولات) في حال تقلب الاتصال
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug("[WAHA SEND IMAGE] attempt=%d session=%s to=%s file=%s", attempt, self.session, recipient_id, filename)
                response = self._post_json(f"{self.base_url}/api/sendImage", payload)
                if response and response.status_code in [200, 201]:
                    logger.info("[WAHA] ✅ Image sent successfully to recipient=%s (session=%s)", recipient_id, self.session)
                    return response
            except Exception as e:
                logger.error("[WAHA IMAGE ERROR] Attempt %s/%s failed: %s", attempt, max_retries, e)

        return None

    # ── file (generic document attachment) ──────────────────────────────────

    def send_file(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str = "application/pdf",
    ):
        raw_data = file_bytes.getvalue() if hasattr(file_bytes, "getvalue") else file_bytes
        logger.debug("[WAHA SEND FILE] session=%s to=%s file=%s", self.session, recipient_id, filename)

        payload = {
            "session": self.session,
            "chatId": recipient_id,
            "file": {
                "mimetype": mime_type,
                "filename": filename,
                "data": base64.b64encode(raw_data).decode("utf-8"),
            },
        }
        return self._post_json(f"{self.base_url}/api/sendFile", payload)

    # ── typing indicator & seen ──────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        logger.debug("[WAHA TYPING] session=%s to=%s", self.session, recipient_id)
        # 1. إرسال إشعار قراءة الرسالة (seen)
        try:
            self._post_json(f"{self.base_url}/api/sendSeen", {"session": self.session, "chatId": recipient_id})
        except Exception:
            pass

        # 2. إرسال مؤشر الكتابة (typing)
        payload = {"session": self.session, "chatId": recipient_id}
        return self._post_json(f"{self.base_url}/api/startTyping", payload)

    # ── media download (prescription image, voice, pdf) ─────────────────────

    def download_media(self, media: dict, media_type: str = "media"):
        try:
            if not media:
                return None

            if media.get("data"):
                return base64.b64decode(media["data"])

            url = media.get("url")
            if url:
                timeout = 30 if media_type in ("pdf", "voice") else 15
                response = requests.get(url, headers=self.headers, timeout=timeout)
                response.raise_for_status()
                return response.content

            return None
        except Exception as e:
            logger.error("[WAHA %s DOWNLOAD ERROR] %s", media_type.upper(), e)
            return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _post_json(self, url: str, payload: dict):
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=30,
            )
            if response.status_code not in [200, 201]:
                logger.error(
                    "[WAHA ERROR] status=%s body=%s",
                    response.status_code, response.text,
                )
            return response
        except Exception as e:
            logger.error("[WAHA ERROR] Connection failed: %s", e)
            return None

    def parse_message(self, payload, page_id):
        from parsers.waha import parse_waha_message
        return parse_waha_message(
            payload,
            page_id,
            platform_id=self.platform_id,
            platform_name=self.platform_name,
        )