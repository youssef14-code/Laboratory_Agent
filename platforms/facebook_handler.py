import io
import json
import logging

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
        filename: str = "ticket.png",
        mime_type: str = "image/png",
    ):
        logger.debug("[FB SEND IMAGE] to=%s file=%s", recipient_id, filename)

        recipient_json = json.dumps({"id": recipient_id})
        message_json   = json.dumps({
            "attachment": {
                "type": "image",
                "payload": {"is_reusable": False},
            }
        })

        try:
            response = requests.post(
                f"{self.base_url}/me/messages",
                params=self.params,
                data={
                    "messaging_type": "RESPONSE",
                    "recipient":      recipient_json,
                    "message":        message_json,
                },
                files={
                    "filedata": (filename, io.BytesIO(file_bytes), mime_type),
                },
                timeout=30,
            )
            if response.status_code not in [200, 201]:
                logger.error(
                    "[FB IMAGE ERROR] status=%s body=%s",
                    response.status_code, response.text,
                )
            return response
        except Exception as e:
            logger.error("[FB IMAGE ERROR] %s", e)
            return None
    # ── typing indicator ─────────────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        """Show typing indicator in Messenger."""
        logger.debug("[FB TYPING] to=%s", recipient_id)
        payload = {
            "recipient":     {"id": recipient_id},
            "sender_action": "typing_on",
        }
        return self._post_json(f"{self.base_url}/me/messages", payload)

    # ── comments ─────────────────────────────────────────────────────────────

    def handle_comment(self, comment_id: str, page_id: str):
        self.react_to_comment(comment_id)
        self.reply_to_comment(comment_id)
        self.send_private_reply(
            page_id,
            self.token,
            comment_id,
            "أهلاً! شكراً على تعليقك، كيف نقدر نساعدك؟"
        )

    def react_to_comment(self, comment_id: str):
        logger.debug("[FB LIKE COMMENT] comment_id=%s", comment_id)
        try:
            response = requests.post(
                f"{self.base_url}/{comment_id}/likes",
                params=self.params,
                timeout=10,
            )
            if response.status_code not in [200, 201]:
                logger.error("[FB LIKE ERROR] status=%s body=%s", response.status_code, response.text)
            return response
        except Exception as e:
            logger.error("[FB LIKE ERROR] %s", e)
            return None

    def reply_to_comment(
        self,
        comment_id: str,
        static_message: str = "شكراً على تعليقك! راسلنا خاصةً للمساعدة. 🙏",
    ):
        """Reply publicly to a comment with a static message."""
        logger.debug("[FB COMMENT REPLY] comment_id=%s", comment_id)
        payload = {"message": static_message}
        return self._post_json(
            f"{self.base_url}/{comment_id}/comments", payload
        )

    def send_private_reply(self, page_id, page_access_token: str, comment_id: str, text: str):
        """
        Send a private reply (Messenger message) to a user who commented on your Page's post.
        Requirements:
          - Use a valid Page access token
          - Comment must be on a Page-owned post
          - Only works within 7 days of the comment
          - Only one private reply per comment
        """
        logger.debug("[FB PRIVATE REPLY] comment_id=%s page_id=%s", comment_id, page_id)

        url = f"{self.base_url}/{page_id}/messages"
        params = {"access_token": page_access_token}
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE"
        }

        response = requests.post(url, params=params, json=payload)

        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}

        if response.status_code not in [200, 201]:
            logger.error("[FB PRIVATE REPLY ERROR] status=%s body=%s", response.status_code, data)

        return {
            "status": response.status_code,
            "ok": response.ok,
            "data": data
        }

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