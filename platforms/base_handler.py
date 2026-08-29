from service.message_processor import run_agent, handle_image_message

class BaseHandler:
    platform_id = None

    def __init__(self, page):
        self.page    = page
        self.page_id = page.page_id
        self.token   = page.token

    def handle(self, message) -> tuple[str | None, bytes | None]:
        if message.type == "text":
            return run_agent(message)
        elif message.type == "image":
            return handle_image_message(message, self.page)
        return self._handle_media(message.type), None

    def _handle_media(self, msg_type: str) -> str:
        responses = {
            "image":    "برجاء إرسال رسالة نصية بدلاً من الصورة.",
            "video":    "برجاء إرسال رسالة نصية بدلاً من الفيديو.",
            "audio":    "برجاء إرسال رسالة نصية بدلاً من الملف الصوتي.",
            "voice":    "برجاء إرسال رسالة نصية بدلاً من الرسالة الصوتية.",
            "location": "📍 تم استلام الموقع.",
        }
        return responses.get(msg_type, "برجاء إرسال رسالة نصية.")

    # ── abstract interface ────────────────────────────────────────────────────

    def send(self, recipient_id: str, text: str):
        raise NotImplementedError

    def send_typing(self, recipient_id: str):
        raise NotImplementedError

    def send_file(self, recipient_id: str, file_bytes: bytes, filename: str, mime_type: str):
        raise NotImplementedError

    def reply_to_comment(self, comment_id: str, static_message: str):
        raise NotImplementedError

    def react_to_comment(self, comment_id: str, reaction_type: str):
        raise NotImplementedError

    def send_private_reply(self, comment_id: str, text: str):
        raise NotImplementedError

    def handle_comment(self, comment_id: str):
        raise NotImplementedError