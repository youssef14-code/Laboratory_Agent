import json
import logging
import os
import time
import redis

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = int(os.environ.get("DEBOUNCE_SECONDS", 7))
DUE_ZSET_KEY = "conversations:due"
DEFAULT_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _conversation_key(platform_id, page_id, sender_id) -> str:
    return f"{platform_id}:{page_id}:{sender_id}"


def _queue_key(conversation_key: str) -> str:
    return f"queue:{conversation_key}"


def get_redis_client(url: str = None) -> redis.Redis:
    redis_url = url or os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    return redis.Redis.from_url(redis_url, decode_responses=True)


def enqueue_message(
    r: redis.Redis,
    platform_id: int,
    page_id: str,
    sender_id: str,
    platform_name: str,
    msg_type: str,
    text: str | None = None,
    media: dict | None = None,
    received_at: float | None = None,
    sender_name: str | None = None,   # 👈 1. أضف هنا
) -> None:
    conversation_key = _conversation_key(platform_id, page_id, sender_id)
    queue_key = _queue_key(conversation_key)

    item = {
        "platform_id": platform_id,
        "page_id": page_id,
        "sender_id": sender_id,
        "platform_name": platform_name,
        "msg_type": msg_type,
        "text": text,
        "media": media,
        "sender_name": sender_name,   # 👈 2. أضف هنا
        "received_at": received_at if received_at is not None else time.time(),
    }
    print(f"👉 [ENQUEUE REDIS] sender_name={sender_name}")
    due_at = time.time() + DEBOUNCE_SECONDS

    pipe = r.pipeline(transaction=True)
    pipe.rpush(queue_key, json.dumps(item, ensure_ascii=False))
    pipe.zadd(DUE_ZSET_KEY, {conversation_key: due_at})
    pipe.execute()

    logger.info(
        "[QUEUE] enqueued | conversation=%s | msg_type=%s | due_in=%.1fs",
        conversation_key, msg_type, DEBOUNCE_SECONDS,
    )