"""
service/redis_worker.py
============================================================================
مسؤولية الملف: سحب المحادثات بعد انتهاء الـ Debounce وتنفيذ كل العمليات:
- فحص الاشتراك
- تشغيل الـ Typing المستمر
- معالجة النصوص والصور المتعددة (Multi-Image OCR)
- تشغيل الـ Agent
- إرسال الرد النصي وتذكرة الحجز
"""

import json
import logging
import os
import socket
import threading
import time
import uuid
import redis

from service.redis_queue import DUE_ZSET_KEY, get_redis_client
from app import app, db
from models.models import Page, Platform
from platforms.waha_handler import WahaHandler
from platforms.facebook_handler import FacebookHandler
from software_service.subscripition_service import SubscriptionService
from service.message_processor import IncomingMessage, handle_multi_image_messages

try:
    from notified_center.EmailSender import send_production_alert
except ImportError:
    def send_production_alert(*args, **kwargs):
        pass

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5
PROCESSING_STALE_SECONDS = 120
RECOVERY_INTERVAL_SECONDS = 30
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _new_owner_token() -> str:
    return f"{WORKER_ID}:{uuid.uuid4().hex}"


def _queue_key(conversation_key: str) -> str:
    return f"queue:{conversation_key}"


def _processing_key(conversation_key: str) -> str:
    return f"processing:{conversation_key}"


def _processing_owner_key(conversation_key: str) -> str:
    return f"processing_owner:{conversation_key}"


def _processing_heartbeat_key(conversation_key: str) -> str:
    return f"processing_heartbeat:{conversation_key}"


def parse_conversation_key(conversation_key: str) -> tuple[int, str, str]:
    platform_id_str, page_id, sender_id = conversation_key.split(":", 2)
    return int(platform_id_str), page_id, sender_id


def build_handler(platform_id: int, page):
    if platform_id == WahaHandler.platform_id or platform_id == 2:
        return WahaHandler(page)
    if platform_id == FacebookHandler.platform_id or platform_id == 1:
        return FacebookHandler(page)
    raise ValueError(f"Unknown platform_id={platform_id}")


# ============================================================================
# Lua Scripts (Locks & Recovery)
# ============================================================================

_CLAIM_SCRIPT = """
local removed = redis.call('ZREM', KEYS[1], ARGV[1])
if removed == 0 then return 0 end
if redis.call('EXISTS', KEYS[3]) == 1 then
    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
    return 0
end
if redis.call('EXISTS', KEYS[2]) == 0 then return 0 end
redis.call('RENAME', KEYS[2], KEYS[3])
redis.call('SET', KEYS[4], ARGV[2])
redis.call('SET', KEYS[5], ARGV[3])
return 1
"""

_HEARTBEAT_SCRIPT = """
local current_owner = redis.call('GET', KEYS[1])
if not current_owner or current_owner ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""

_FINISH_SCRIPT = """
local current_owner = redis.call('GET', KEYS[2])
if not current_owner or current_owner ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])
return 1
"""

_RECOVER_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
local owner = redis.call('GET', KEYS[4])
local heartbeat = redis.call('GET', KEYS[5])
if not owner or not heartbeat then return 0 end
local age = tonumber(ARGV[2]) - tonumber(heartbeat)
if age < tonumber(ARGV[3]) then return 0 end
while redis.call('LLEN', KEYS[1]) > 0 do
    local item = redis.call('RPOP', KEYS[1])
    redis.call('LPUSH', KEYS[2], item)
end
redis.call('ZADD', KEYS[3], ARGV[2], ARGV[1])
redis.call('DEL', KEYS[4])
redis.call('DEL', KEYS[5])
return 1
"""


def claim_due_conversations(r: redis.Redis, claim_script) -> list[tuple[str, str]]:
    now = time.time()
    candidates = r.zrangebyscore(DUE_ZSET_KEY, "-inf", now)
    claimed: list[tuple[str, str]] = []

    for conversation_key in candidates:
        owner_token = _new_owner_token()
        result = claim_script(
            keys=[
                DUE_ZSET_KEY,
                _queue_key(conversation_key),
                _processing_key(conversation_key),
                _processing_owner_key(conversation_key),
                _processing_heartbeat_key(conversation_key),
            ],
            args=[conversation_key, owner_token, now],
        )
        if result == 1:
            claimed.append((conversation_key, owner_token))
            logger.info("[WORKER CLAIM] worker=%s conversation=%s", WORKER_ID, conversation_key)

    return claimed


def _heartbeat(r: redis.Redis, conversation_key: str, owner_token: str, heartbeat_script) -> bool:
    result = heartbeat_script(
        keys=[_processing_owner_key(conversation_key), _processing_heartbeat_key(conversation_key)],
        args=[owner_token, time.time()],
    )
    return result == 1


def _require_ownership(r: redis.Redis, conversation_key: str, owner_token: str, heartbeat_script) -> None:
    if not _heartbeat(r, conversation_key, owner_token, heartbeat_script):
        raise RuntimeError(f"Worker lost ownership of conversation={conversation_key}")


def _finish_processing(r: redis.Redis, conversation_key: str, owner_token: str, finish_script) -> bool:
    result = finish_script(
        keys=[
            _processing_key(conversation_key),
            _processing_owner_key(conversation_key),
            _processing_heartbeat_key(conversation_key),
        ],
        args=[owner_token],
    )
    return result == 1


# ============================================================================
# معالجة المحادثة بنفس منطقك القديم بالظبط
# ============================================================================

def process_conversation(r: redis.Redis, conversation_key: str, owner_token: str, heartbeat_script, finish_script) -> None:
    platform_id, page_id, sender_id = parse_conversation_key(conversation_key)
    processing_key = _processing_key(conversation_key)

    with app.app_context():
        try:
            _require_ownership(r, conversation_key, owner_token, heartbeat_script)
            raw_items = r.lrange(processing_key, 0, -1)

            if not raw_items:
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            entries = [json.loads(raw) for raw in raw_items]
            entries.sort(key=lambda entry: entry.get("received_at", 0))

            # البحث عن الصفحة
            page = Page.query.filter_by(page_id=page_id, platform_id=platform_id).first()
            if not page and platform_id == 2:  # WhatsApp fallback
                page = Page.query.filter_by(platform_id=platform_id).first()

            if not page:
                logger.error("[WORKER] page not found | page_id=%s | platform_id=%s", page_id, platform_id)
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            handler = build_handler(platform_id, page)

            # 1️⃣ فحص باقة الاشتراك (نفس كودك القديم)
            subscription = SubscriptionService.get_by_page(page)
            allowed, _ = SubscriptionService.can_use_ai(subscription)
            if not allowed:
                logger.warning("[WORKER] Subscription limit reached for lab_id=%s", page.laboratory_id)
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            # تجهيز الرسائل والصور المجمعة
            texts = []
            images = []
            last_message_obj = None

            for entry in entries:
                msg_obj = IncomingMessage(
                    sender_id=sender_id,
                    page_id=page_id,
                    platform_id=platform_id,
                    platform_name=entry.get("platform_name"),
                    msg_type=entry.get("msg_type"),
                    text=entry.get("text"),
                    media=entry.get("media"),
                    sender_name=entry.get("sender_name"),  # 👈 أضف هنا
                )
                last_message_obj = msg_obj
                if entry.get("text"):
                    texts.append(entry.get("text"))
                if entry.get("msg_type") == "image" or entry.get("media"):
                    images.append(msg_obj)

            combined_text = " \n ".join(texts).strip()

            # 2️⃣ تشغيل إشارة الكتابة (Typing) بشكل مستمر أثناء المعالجة (نفس كودك القديم)
            stop_typing = threading.Event()

            def keep_typing():
                while not stop_typing.is_set():
                    handler.send_typing(sender_id)
                    stop_typing.wait(3.0)

            typing_thread = threading.Thread(target=keep_typing, daemon=True)
            typing_thread.start()

            reply = None
            ticket_bytes = None

            try:
                # 🖼️ 3️⃣ اختيار المعالجة حسب الصور المرسلة (نفس كودك القديم بالظبط)
                if len(images) > 1:
                    reply, ticket_bytes = handle_multi_image_messages(images, page, combined_text)
                elif len(images) == 1:
                    final_message = images[0]
                    final_message.text = combined_text or getattr(final_message, "text", "")
                    reply, ticket_bytes = handler.handle(final_message)
                elif last_message_obj:
                    final_message = last_message_obj
                    final_message.text = combined_text
                    reply, ticket_bytes = handler.handle(final_message)
                else:
                    return

            finally:
                stop_typing.set()
                typing_thread.join(timeout=1.0)

            # 💬 4️⃣ إرسال الرد النصي للعميل (نفس كودك القديم)
            if reply:
                handler.send(sender_id, reply)

            # 🎫 5️⃣ إرسال تذكرة الحجز إن وجدت (نفس كودك القديم)
            if ticket_bytes:
                handler.send_image(
                    recipient_id=sender_id,
                    file_bytes=ticket_bytes,
                    filename="booking_ticket.png",
                )

            logger.info(
                "[WORKER] sent reply to sender=%s has_reply=%s has_ticket=%s",
                sender_id,
                bool(reply),
                bool(ticket_bytes),
            )

            _require_ownership(r, conversation_key, owner_token, heartbeat_script)
            _finish_processing(r, conversation_key, owner_token, finish_script)

        except Exception as e:
            db.session.rollback()
            logger.exception("[WORKER] Processing error for conversation=%s", conversation_key)
            try:
                send_production_alert(
                    subject="Redis Worker Processing Failure",
                    body_or_error=e,
                    context={"conversation_key": conversation_key, "worker_id": WORKER_ID},
                )
            except Exception:
                pass
        finally:
            db.session.remove()


# ============================================================================
# Recovery & Worker Loop
# ============================================================================

def recover_stale_processing(r: redis.Redis, recover_script) -> None:
    now = time.time()
    for heartbeat_key in r.scan_iter(match="processing_heartbeat:*"):
        conversation_key = heartbeat_key.split("processing_heartbeat:", 1)[1]
        recover_script(
            keys=[
                _processing_key(conversation_key),
                _queue_key(conversation_key),
                DUE_ZSET_KEY,
                _processing_owner_key(conversation_key),
                heartbeat_key,
            ],
            args=[conversation_key, now, PROCESSING_STALE_SECONDS],
        )


def run_worker_forever(r: redis.Redis) -> None:
    claim_script = r.register_script(_CLAIM_SCRIPT)
    heartbeat_script = r.register_script(_HEARTBEAT_SCRIPT)
    finish_script = r.register_script(_FINISH_SCRIPT)
    recover_script = r.register_script(_RECOVER_SCRIPT)

    last_recovery_check = 0.0
    logger.info("[WORKER] started | worker=%s", WORKER_ID)

    while True:
        try:
            claimed = claim_due_conversations(r, claim_script)
            for conversation_key, owner_token in claimed:
                process_conversation(r, conversation_key, owner_token, heartbeat_script, finish_script)

            now = time.time()
            if now - last_recovery_check >= RECOVERY_INTERVAL_SECONDS:
                recover_stale_processing(r, recover_script)
                last_recovery_check = now
        except Exception:
            logger.exception("[WORKER] unexpected error in main loop")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    redis_client = get_redis_client()
    run_worker_forever(redis_client)