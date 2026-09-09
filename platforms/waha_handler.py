import base64
import logging
import os

import requests

from platforms.base_handler import BaseHandler
from notified_center import send_production_alert, WahaAPIException, MediaDownloadException

logger = logging.getLogger(__name__)


class WahaHandler(BaseHandler):
    platform_id = 2

    def __init__(self, page):
        super().__init__(page)
        self.base_url = self._resolve_base_url(getattr(page, "page_id", None))
        self.session  =  "default"
        self.headers  = {
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

    def send(self, recipient_id: str, text: str):
        if not text or not text.strip():
            return None

        logger.debug("[WAHA SEND] to=%s", recipient_id)

        payload = {
            "session": self.session,
            "chatId":  recipient_id,
            "text":    str(text),
        }
        return self._post_json(f"{self.base_url}/api/sendText", payload)

    # ── image (booking ticket, or any photo) ────────────────────────────────

    def send_image(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str = "ticket.png",
        mime_type: str = "image/png",
    ):
        logger.debug("[WAHA SEND IMAGE] to=%s file=%s", recipient_id, filename)

        payload = {
            "session": self.session,
            "chatId":  recipient_id,
            "file": {
                "mimetype": mime_type,
                "filename": filename,
                "data":     base64.b64encode(file_bytes).decode("utf-8"),
            },
        }
        return self._post_json(f"{self.base_url}/api/sendImage", payload)

    # ── file (generic document attachment) ──────────────────────────────────

    def send_file(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str = "application/pdf",
    ):
        logger.debug("[WAHA SEND FILE] to=%s file=%s", recipient_id, filename)

        payload = {
            "session": self.session,
            "chatId":  recipient_id,
            "file": {
                "mimetype": mime_type,
                "filename": filename,
                "data":     base64.b64encode(file_bytes).decode("utf-8"),
            },
        }
        return self._post_json(f"{self.base_url}/api/sendFile", payload)

    # ── typing indicator ─────────────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        logger.debug("[WAHA TYPING] to=%s", recipient_id)
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
            logger.exception("[WAHA %s DOWNLOAD ERROR] %s", media_type.upper(), e)
            send_production_alert(
                subject=f"WAHA Media Download Error ({media_type})",
                body_or_error=e,
                context={"page_id": getattr(self.page, "page_id", None), "media_type": media_type},
            )
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
                send_production_alert(
                    subject="WAHA API HTTP Error",
                    body_or_error=f"HTTP {response.status_code}: {response.text}",
                    context={"url": url, "page_id": getattr(self.page, "page_id", None), "recipient_id": payload.get("chatId")},
                )
            return response
        except Exception as e:
            logger.exception("❌ [WAHA ERROR] Connection failed: %s", e)
            send_production_alert(
                subject="WAHA Connection Exception",
                body_or_error=e,
                context={"url": url, "page_id": getattr(self.page, "page_id", None), "recipient_id": payload.get("chatId")},
            )
            return None

    def parse_message(self, payload, page_id):
        from parsers.waha import parse_waha_message
        return parse_waha_message(
            payload,
            page_id,
            platform_id=self.platform_id,
            platform_name=self.platform_name,
        )