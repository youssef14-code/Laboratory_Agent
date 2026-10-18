import os
import uuid
import requests
from urllib.parse import quote
import time
from graph.agent_response import AgentResponse
from graph.graph import get_agent_graph
from graph.utils import count_request
from ocr.processor import process_prescription_ocr
from software_service.client_services import ClientService
import logging
logger = logging.getLogger(__name__)

FACEBOOK_GRAPH_API_VERSION = "v19.0"


class IncomingMessage:
    def __init__(
        self,
        sender_id,
        page_id,
        platform_id,
        msg_type,
        text=None,
        media=None,
        platform_name=None,
        sender_name=None,
        session=None,         # WAHA session name (from webhook payload["session"])
        sender_phone=None,    # real phone from webhook payload (SenderAlt / remoteJidAlt) if present
    ):
        self.sender_id = sender_id
        self.page_id = page_id
        self.platform_id = platform_id
        self.platform_name = platform_name
        self.type = msg_type
        self.text = text
        self.media = media
        self.sender_name = sender_name
        self.session = session
        self.sender_phone = sender_phone


# Pricing per model (USD per token)
OCR_INPUT_COST_PER_TOKEN = 0.3 / 1_000_000
OCR_OUTPUT_COST_PER_TOKEN = 2.5 / 1_000_000

FLASH_INPUT_COST_PER_TOKEN = 0.25 / 1_000_000
FLASH_OUTPUT_COST_PER_TOKEN = 1.5 / 1_000_000


def _calc_total_usage(result: dict, ocr_usage: dict = None) -> dict:
    """حساب استهلاك التوكنز والتكلفة لجميع النودات."""
    nodes = [
        ("ocr_vision_usage", ocr_usage),
        ("intent_usage", result.get("intent_usage")),
        ("retrieval_usage", result.get("retrieval_usage")),
        ("booking_usage", result.get("booking_usage")),
        ("complaint_usage", result.get("complaint_usage")),
        ("direct_usage", result.get("direct_usage")),
        ("inquiry_usage", result.get("inquiry_usage")),
        ("labresults_usage", result.get("labresults_usage")),
    ]

    total_in = total_out = total = 0
    total_cost_usd = 0.0
    breakdown = {}

    for key, u in nodes:
        if not u:
            continue
        i = u.get("input_tokens", 0) or 0
        o = u.get("output_tokens", 0) or 0
        t = u.get("total_tokens", 0) or (i + o)

        if not (i or o):
            continue

        if key == "ocr_vision_usage":
            in_rate, out_rate = OCR_INPUT_COST_PER_TOKEN, OCR_OUTPUT_COST_PER_TOKEN
        else:
            in_rate, out_rate = FLASH_INPUT_COST_PER_TOKEN, FLASH_OUTPUT_COST_PER_TOKEN

        node_cost = (i * in_rate) + (o * out_rate)

        breakdown[key] = {
            "input": i,
            "output": o,
            "total": t,
            "cost_usd": node_cost,
        }

        total_in += i
        total_out += o
        total += t
        total_cost_usd += node_cost

    total_cost_cents = total_cost_usd * 100
    req_per_dollar = int(1.0 / total_cost_usd) if total_cost_usd > 0 else 0

    return {
        "breakdown": breakdown,
        "total_input": total_in,
        "total_output": total_out,
        "total_tokens": total,
        "total_cost_usd": total_cost_usd,
        "total_cost_cents": total_cost_cents,
        "req_per_dollar": req_per_dollar,
    }


def _is_empty_identity_name(value) -> bool:
    """Return True when a profile name is not usable."""
    if value is None:
        return True

    value = str(value).strip().lower()
    return value in {"", "none", "null", "unknown"}


def _extract_whatsapp_phone(value) -> str | None:
    """Extract a real phone from a WhatsApp JID (…@c.us / …@s.whatsapp.net).

    Examples:
        201505202239@c.us -> 201505202239
        201505202239@s.whatsapp.net -> 201505202239

    A LID is never treated as a phone number.
    """
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    domain = None
    if "@" in raw:
        raw, domain = raw.split("@", 1)

    if domain and domain.lower() == "lid":
        return None

    return raw if raw.isdigit() else None


def _get_phone_from_waha_lid(sender: str, session_name: str, page_id=None) -> str | None:
    """Resolve a WhatsApp LID to the real phone number through the right WAHA container."""
    from platforms.waha_handler import WahaHandler

    base_url = WahaHandler._resolve_base_url(page_id)
    headers = {"X-Api-Key": os.environ.get("WAHA_API_KEY", "")}
    url = (
        f"{base_url}/api/{quote(str(session_name), safe='')}"
        f"/lids/{quote(str(sender), safe='')}"
    )

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            logger.warning("LID lookup failed: status=%s url=%s", response.status_code, url)
            return None

        data = response.json()
        pn = data.get("pn") if isinstance(data, dict) else None
        phone = _extract_whatsapp_phone(pn)
        if not phone:
            logger.warning("LID lookup returned no phone (pn=%r) for %s", pn, sender)
        return phone

    except (requests.RequestException, ValueError):
        logger.exception("LID lookup error url=%s", url)
        return None


def _get_client_identity(message: IncomingMessage, page) -> str:
    """Return a real WhatsApp phone number or a Facebook profile name.

    WhatsApp order:
      1. Phone from webhook payload (sender_phone), if present.
      2. Existing @c.us or @s.whatsapp.net phone ID.
      3. Resolve @lid (or bare number) through WAHA.
      4. Return an empty string if a real phone cannot be obtained.

    A numeric LID is never returned as if it were a phone number.
    """
    platform = (getattr(message, "platform_name", None) or "").lower()
    platform_id = getattr(message, "platform_id", None)
    sender = str(getattr(message, "sender_id", None) or "").strip()
    sender_name = getattr(message, "sender_name", None)
    msg_session = getattr(message, "session", None)

    # ───────────── WhatsApp ─────────────
    if platform == "whatsapp" or platform_id == 2:
        sender_lower = sender.lower()
        session_name = msg_session or os.environ.get("WAHA_SESSION", "") or "default"
        page_id = getattr(message, "page_id", None)

        # 1. phone from webhook payload (if present)
        alt_phone = _extract_whatsapp_phone(getattr(message, "sender_phone", None))
        if alt_phone:
            return alt_phone

        # 2. already a real phone JID
        if "@c.us" in sender_lower or "@s.whatsapp.net" in sender_lower:
            phone = _extract_whatsapp_phone(sender)
            if phone:
                return phone

        # 3. LID (with suffix) or bare digits -> resolve through WAHA
        if "@lid" in sender_lower or sender.isdigit():
            return _get_phone_from_waha_lid(sender, session_name, page_id) or ""

        return ""

    # ───────────── Facebook / Messenger ─────────────
    if platform in {"facebook", "messenger"} or platform_id == 1:
        token = getattr(page, "token", None)
        page_id = getattr(page, "page_id", None)

        if not token:
            logger.warning(
                "[FB Identity] Page access token is missing; cannot look up profile name | page_id=%s",
                page_id,
            )
        elif not sender:
            logger.warning(
                "[FB Identity] Sender ID is missing; cannot look up profile name | page_id=%s",
                page_id,
            )
        else:
            try:
                url = f"https://graph.facebook.com/{FACEBOOK_GRAPH_API_VERSION}/{sender}"
                response = requests.get(
                    url,
                    params={
                        "fields": "first_name,last_name",
                        "access_token": token,
                    },
                    timeout=5,
                )
                try:
                    data = response.json()
                except ValueError:
                    logger.error(
                        "[FB Identity] Graph API returned non-JSON response | api_version=%s page_id=%s sender_id=%s status=%s",
                        FACEBOOK_GRAPH_API_VERSION,
                        page_id,
                        sender,
                        response.status_code,
                    )
                else:
                    if response.status_code == 200 and isinstance(data, dict):
                        name = data.get("name")
                        if not name:
                            name = (
                                f"{data.get('first_name') or ''} "
                                f"{data.get('last_name') or ''}"
                            ).strip()
                        if name:
                            logger.info(
                                "[FB Identity] Profile name lookup succeeded | api_version=%s page_id=%s sender_id=%s",
                                FACEBOOK_GRAPH_API_VERSION,
                                page_id,
                                sender,
                            )
                            return name

                        logger.warning(
                            "[FB Identity] Graph API succeeded but returned no profile name | api_version=%s page_id=%s sender_id=%s response_fields=%s",
                            FACEBOOK_GRAPH_API_VERSION,
                            page_id,
                            sender,
                            sorted(data.keys()),
                        )
                    else:
                        error = data.get("error") if isinstance(data, dict) else None
                        if isinstance(error, dict):
                            logger.error(
                                "[FB Identity] Profile lookup failed | api_version=%s page_id=%s sender_id=%s status=%s type=%s code=%s subcode=%s message=%s fbtrace_id=%s",
                                FACEBOOK_GRAPH_API_VERSION,
                                page_id,
                                sender,
                                response.status_code,
                                error.get("type"),
                                error.get("code"),
                                error.get("error_subcode"),
                                error.get("message"),
                                error.get("fbtrace_id"),
                            )

                            if response.status_code != 200:
                                try:
                                    token_check = requests.get(
                                        f"https://graph.facebook.com/{FACEBOOK_GRAPH_API_VERSION}/me",
                                        params={
                                            "fields": "id",
                                            "access_token": token,
                                        },
                                        timeout=5,
                                    )
                                    try:
                                        token_data = token_check.json()
                                    except ValueError:
                                        logger.error(
                                            "[FB Identity] Token/version diagnostic returned non-JSON | api_version=%s page_id=%s status=%s",
                                            FACEBOOK_GRAPH_API_VERSION,
                                            page_id,
                                            token_check.status_code,
                                        )
                                    else:
                                        token_error = (
                                            token_data.get("error")
                                            if isinstance(token_data, dict)
                                            else None
                                        )
                                        if token_check.status_code == 200 and isinstance(token_data, dict) and token_data.get("id"):
                                            token_page_id = str(token_data["id"])
                                            logger.info(
                                                "[FB Identity] Token/version diagnostic succeeded | api_version=%s token_accepted=true token_page_id=%s configured_page_id=%s page_match=%s; API version and token work for /me, so investigate sender profile access.",
                                                FACEBOOK_GRAPH_API_VERSION,
                                                token_page_id,
                                                page_id,
                                                token_page_id == str(page_id),
                                            )
                                        elif isinstance(token_error, dict):
                                            token_error_code = token_error.get("code")
                                            if token_error_code in (190, 102):
                                                diagnosis = "token rejected, invalid, or expired"
                                            elif "version" in str(token_error.get("message", "")).lower():
                                                diagnosis = "Graph API version may be unsupported"
                                            else:
                                                diagnosis = "token and API version could not be verified"
                                            logger.error(
                                                "[FB Identity] Token/version diagnostic failed | diagnosis=%s api_version=%s page_id=%s status=%s type=%s code=%s subcode=%s message=%s fbtrace_id=%s",
                                                diagnosis,
                                                FACEBOOK_GRAPH_API_VERSION,
                                                page_id,
                                                token_check.status_code,
                                                token_error.get("type"),
                                                token_error_code,
                                                token_error.get("error_subcode"),
                                                token_error.get("message"),
                                                token_error.get("fbtrace_id"),
                                            )
                                        else:
                                            logger.error(
                                                "[FB Identity] Token/version diagnostic returned unexpected response | api_version=%s page_id=%s status=%s response_type=%s",
                                                FACEBOOK_GRAPH_API_VERSION,
                                                page_id,
                                                token_check.status_code,
                                                type(token_data).__name__,
                                            )
                                except requests.RequestException as diagnostic_error:
                                    logger.error(
                                        "[FB Identity] Token/version diagnostic request failed | api_version=%s page_id=%s error_type=%s",
                                        FACEBOOK_GRAPH_API_VERSION,
                                        page_id,
                                        type(diagnostic_error).__name__,
                                    )
                        else:
                            logger.error(
                                "[FB Identity] Profile lookup returned unexpected response | api_version=%s page_id=%s sender_id=%s status=%s response_type=%s",
                                FACEBOOK_GRAPH_API_VERSION,
                                page_id,
                                sender,
                                response.status_code,
                                type(data).__name__,
                            )

            except requests.RequestException as request_error:
                logger.error(
                    "[FB Identity] Graph API request failed | api_version=%s page_id=%s sender_id=%s error_type=%s",
                    FACEBOOK_GRAPH_API_VERSION,
                    page_id,
                    sender,
                    type(request_error).__name__,
                )

        if not _is_empty_identity_name(sender_name):
            logger.info(
                "[FB Identity] Using sender name from incoming message | page_id=%s sender_id=%s",
                page_id,
                sender,
            )
            return str(sender_name).strip()

        logger.warning(
            "[FB Identity] No profile name available; falling back to sender ID | page_id=%s sender_id=%s",
            page_id,
            sender,
        )
        return sender

    return sender


def _consume_subscription(message: "IncomingMessage", usage: dict) -> None:
    """خصم استهلاك الرسالة من باقة المختبر."""
    try:
        from software_service.subscripition_service import SubscriptionService
        from models.models import Page

        page = Page.query.filter_by(
            page_id=message.page_id,
            platform_id=message.platform_id,
        ).first()

        if not page:
            print(f"[_consume_subscription] No page found for page_id={message.page_id}")
            return

        subscription = SubscriptionService.get_by_page(page)

        if not subscription:
            print(f"[_consume_subscription] No subscription found for laboratory_id={page.laboratory_id}")
            return

        SubscriptionService.consume(
            subscription,
            cost=usage["total_cost_usd"],
        )

    except Exception as e:
        print(f"[_consume_subscription] Error: {e}")


def _consume_subscription_direct(message: "IncomingMessage", count: int = 1) -> None:
    """خصم رسائل من الاشتراك مباشرة بعدد محدد (بدون حساب tokens)."""
    try:
        from software_service.subscripition_service import SubscriptionService
        from models.models import Page

        page = Page.query.filter_by(
            page_id=message.page_id,
            platform_id=message.platform_id,
        ).first()

        if not page:
            return

        subscription = SubscriptionService.get_by_page(page)
        if not subscription:
            return

        SubscriptionService.consume(subscription, count=count, cost=None)
        print(f"[_consume_subscription_direct] ✅ Consumed {count} message(s) from subscription.")

    except Exception as e:
        print(f"[_consume_subscription_direct] Error: {e}")


def run_agent(message: IncomingMessage, ocr_usage: dict = None) -> tuple[str, bytes | None]:

    from models.models import Page
    page = Page.query.filter_by(
        platform_id=message.platform_id,
        page_id=message.page_id,
    ).first()

    # 1. استخراج كائن العميل بأمان
    client, client_msg = ClientService.get_or_create_client(
        sender_id=message.sender_id,
        page_id=message.page_id,
        platform_id=message.platform_id,
    )

    print("=" * 80)
    print("RUN_AGENT")
    print("Platform :", message.platform_id)
    print("Page     :", message.page_id)
    print("Sender   :", message.sender_id)
    print("Client   :", client)
    print("=" * 80)

    # استخراج الملخص السابق بأمان
    current_summary = client.summary if (client and hasattr(client, "summary") and client.summary) else ""
    current_last_bot = client.last_bot_message if (client and hasattr(client, "last_bot_message") and client.last_bot_message) else ""

    history_rows, _ = ClientService.get_chat_history(
        platform_id=message.platform_id,
        page_id=message.page_id,
        sender_id=message.sender_id,
        limit=7,  # آخر 7 رسائل متبادلة (User / Bot)
    )
    formatted_chat_history = ClientService.format_chat_history(history_rows)
    platform_name = message.platform_name or str(message.platform_id)

    # 🛡️ حماية من تمرير Base64 إلى الموديل
    user_msg_clean = str(message.text or "").strip()
    if user_msg_clean.startswith(("/9j/", "data:image", "JVBERi0", "iVBORw")) or len(user_msg_clean) > 3000:
        user_msg_clean = "📷 [صورة مرفقة]"
    summary_clean = str(current_summary or "").strip()
    if summary_clean.startswith(("/9j/", "data:image")) or len(summary_clean) > 3000:
        summary_clean = summary_clean[:1000]

    sender_identity = _get_client_identity(message, page)

    # 2. تجهيز الـ State الموحدة
    state = {
        "page_id": str(message.page_id),
        "sender_id": str(message.sender_id),
        "sender_name": getattr(message, "sender_name", None),
        "platform_id": message.platform_id,
        "platform_name": platform_name,
        "user_message": user_msg_clean,
        "summary": summary_clean,
        "last_bot_message": current_last_bot,
        "chat_history": formatted_chat_history,
        "sender_identity": sender_identity,  # 👈 تمرير هوية المتحدث

        "intent": None,
        "refined_queries": [],

        "rag_context": "",
        "search_results": [],
        "top_score": 0.0,

        "response": None,

        "intent_usage": None,
        "retrieval_usage": None,
        "booking_usage": None,
        "complaint_usage": None,
        "direct_usage": None,
        "inquiry_usage": None,
        "labresults_usage": None,

        "visit_saved": None,
        "complaint_saved": None,
        "inquiry_saved": None,
        "direct_saved": None,
        "labresults_saved": None,
        "booking_image": None,
        "visit_reference": None,
    }

    call_start_time = time.perf_counter()

    try:
        result = get_agent_graph().invoke(state)
        response_obj = AgentResponse.from_result(result)
    except Exception as e:
        print(f"[run_agent] Error: {e}")
        import traceback
        traceback.print_exc()

        from notified_center.EmailSender import send_production_alert
        send_production_alert(
            subject="Agent Graph Execution Failure in message_processor",
            body_or_error=e,
            context={
                "sender_id": message.sender_id,
                "page_id": message.page_id,
                "platform_id": message.platform_id,
            },
        )
        return "عذرًا، حدث خطأ مؤقت. يرجى المحاولة مرة أخرى.", None

    total_latency_sec = time.perf_counter() - call_start_time
    total_latency_ms = int(total_latency_sec * 1000)

    usage = _calc_total_usage(result, ocr_usage=ocr_usage)

    # 🚨 تنبيه فوري عبر الإيميل لو استهلاك الريكويست تجاوز 30,000 توكن
    TOKEN_ALERT_THRESHOLD = int(os.environ.get("TOKEN_ALERT_THRESHOLD", 30000))
    if usage["total_tokens"] >= TOKEN_ALERT_THRESHOLD:
        try:
            from notified_center.EmailSender import send_production_alert
            breakdown_lines = [
                f"  • {node}: {u['total']:,} tokens (In: {u['input']:,} | Out: {u['output']:,}) -> ${u['cost_usd']:.6f}"
                for node, u in usage["breakdown"].items()
            ]
            breakdown_str = "\n".join(breakdown_lines)
            alert_body = (
                f"⚠️ HIGH TOKEN CONSUMPTION ALERT!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Total Tokens : {usage['total_tokens']:,} (Threshold: {TOKEN_ALERT_THRESHOLD:,})\n"
                f"• Total Cost   : ${usage['total_cost_usd']:.6f} USD ({usage['total_cost_cents']:.4f}¢)\n"
                f"• Intent       : {result.get('intent')}\n\n"
                f"📊 Breakdown per Node:\n{breakdown_str}\n\n"
                f"💬 User Message:\n{message.text or '(No text)'}"
            )
            send_production_alert(
                subject=f"⚠️ High Token Alert ({usage['total_tokens']:,} tokens)",
                body_or_error=alert_body,
                context={
                    "sender_id": message.sender_id,
                    "page_id": message.page_id,
                    "platform": platform_name,
                    "intent": result.get("intent"),
                },
            )
            print(f"🚨 [ALERT SENT] High token usage alert sent ({usage['total_tokens']:,} tokens).")
        except Exception as alert_err:
            print(f"[run_agent] Failed to send high token alert: {alert_err}")

    # خصم الاستهلاك من الاشتراك
    _consume_subscription(message, usage)

    print("\n" + "=" * 76)
    print(" ⚡ REAL-TIME REQUEST METRICS & COST ANALYSIS")
    print(f" 👤 Sender ID: {message.sender_id} | Platform: {platform_name} | Intent: {result.get('intent')}")
    print("-" * 76)
    print(" 🔹 Node Breakdown:")
    # ══════════════════════════════════════════════════════════════════════════
    # ⏱️ طباعة تفاصيل الوقت والسرعة والتكلفة في التيرمنال
    # ══════════════════════════════════════════════════════════════════════════
    node_timings = result.get("node_timings") or {}
    print(" ⏱️ تفاصيل زمن المعالجة (LATENCY BREAKDOWN):")
    nodes_list = list(node_timings.items())
    for idx, (node_name, duration) in enumerate(nodes_list):
        prefix = "└─" if idx == len(nodes_list) - 1 else "├─"
        ms = int(duration * 1000)
        print(f"    {prefix} ⏳ {node_name:<20} : {duration:>6.2f}s  ({ms:>5,} ms)")
    print(" " + "─" * 74)
    print(f" ⚡ TOTAL REQUEST LATENCY    : {total_latency_sec:>6.2f}s  ({total_latency_ms:>5,} ms)")
    print("-" * 76)

    # =========================================================================
    # 🖨️ طباعة الـ Refined Queries والـ Summary والـ Last Bot Reply في التيرمنال
    # =========================================================================
    refined_q = result.get("refined_queries") or []
    queries_summary = [getattr(q, "query", str(q)) for q in refined_q] if refined_q else []
    print("\n" + "═" * 75)
    print(" 📊 تفاصيل المعالجة والذاكرة (AGENT TRACE & MEMORY)")
    print("═" * 75)
    print(f" 🔍 Refined Queries : {queries_summary or '[] (لم يتم استخراج تحاليل محددة)'}")
    print(f" 🧭 Intent          : {result.get('intent')}")
    print("─" * 75)
    print(f" 📜 Current Chat History :\n{formatted_chat_history or '(لا يوجد سجل محادثة سابق)'}")
    print("─" * 75)
    print(f" 🧠 Current Summary :\n{result.get('summary') or '(لا يوجد ملخص)'}")
    print("─" * 75)
    print(f" 🤖 Last Bot Reply  :\n{result.get('last_bot_message') or response_obj.response}")
    print("═" * 75 + "\n", flush=True)
    # =========================================================================
    for node, u in usage["breakdown"].items():
        print(f"    └─ {node:<22} in={u['input']:>5} | out={u['output']:>5} | total={u['total']:>6} | cost=${u['cost_usd']:.8f}")
    print("-" * 76)
    print(" 📊 TOTAL REAL REQUEST METRICS:")
    print(f"    - Input Tokens  : {usage['total_input']:,}")
    print(f"    - Output Tokens : {usage['total_output']:,}")
    print(f"    - Total Tokens  : {usage['total_tokens']:,}")
    print(f"    - Real Cost     : ${usage['total_cost_usd']:.8f} USD ({usage['total_cost_cents']:.5f}¢ cents)")
    print("=" * 76 + "\n", flush=True)

    # إرجاع نص الرد وصورة تذكرة الحجز إن وجدت
    ticket_image = result.get("booking_image") or result.get("booking_pdf") or result.get("booking_ticket")

    return response_obj.response, ticket_image


def handle_image_message(message: IncomingMessage, page) -> tuple[str, bytes | None]:
    """معالجة صورة روشتة واحدة واستخراج التحاليل وتوجيه الـ Agent بالفورمات المطلوب."""
    image_bytes = None

    try:
        # 1. WhatsApp
        if (message.platform_name or "").lower() == "whatsapp":
            from platforms.waha_handler import WahaHandler

            handler = WahaHandler(page)
            image_bytes = handler.download_media(message.media, "image")

            if not image_bytes:
                return "عذرًا، فشل تحميل الصورة المرفقة. يرجى المحاولة مرة أخرى.", None

        # 2. Facebook / Messenger
        else:
            image_url = message.media.get("url") if message.media else None

            if not image_url:
                return "برجاء إرسال صورة روشتة صالحة.", None

            print(f"[handle_image_message] Downloading image: {image_url}")

            img_res = requests.get(image_url, timeout=30)

            if img_res.status_code != 200:
                return "عذرًا، فشل تحميل الصورة المرفقة. يرجى المحاولة مرة أخرى.", None

            image_bytes = img_res.content

        # 3. حفظ الصورة
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        uploads_dir = os.path.join(project_dir, "static", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.jpg"
        image_path = os.path.join(uploads_dir, filename)

        with open(image_path, "wb") as f:
            f.write(image_bytes)

        client_identifier = _get_client_identity(message, page)

        # 4. تشغيل OCR
        ocr_result = process_prescription_ocr(
            image_path=image_path,
            phone_number=client_identifier,
            comes_from=f"{message.platform_name}:{message.sender_id}:{message.page_id}",
            laboratory_id=page.laboratory_id,
        )

        ocr_usage = ocr_result.get("ocr_usage")

        # ✅ 1. روشتة ناجحة ومقروءة -> توجيه الـ Agent بالفورمات المحدد
        if ocr_result.get("success"):
            extracted_tests = [t for t in (ocr_result.get("services_mentioned") or []) if t]
            tests_list = ", ".join(extracted_tests) if extracted_tests else ocr_result.get("extracted_text", "")
            message.text = (
                "[تم استخراج التحاليل التالية من صورة الروشتة المرفقة]:\n"
                f"{tests_list}\n\n"
                "برجاء الرد باللغة العربية (اللهجة المصرية) وتوضيح تفاصيل التحاليل والتحضيرات المطلوبة والأسعار وعرض حجز الزيارة المنزلية."
            )
            logger.info("[handle_image_message] : %s", tests_list)
            result_text, ticket = run_agent(message, ocr_usage=ocr_usage)
            _consume_subscription_direct(message, count=1)
            return result_text, ticket

        # ⏳ 2. صورة روشتة لكن الخط غير مقروء -> تحويل للطبيب
        if ocr_result.get("classified_as") == "prescription":
            static_reply = "لقد استلمنا صورتك وسيقوم الطبيب بمراجعتها والرد عليك."
            user_display_msg = message.text or "📷 [تم إرسال صورة روشتة طبية]"

            ClientService.save_chat_exchange(
                platform_id=message.platform_id,
                page_id=message.page_id,
                sender_id=message.sender_id,
                user_message=user_display_msg,
                bot_reply=static_reply,
                summary="User uploaded a prescription image. Waiting for manual doctor review on dashboard.",
            )

            count_request()
            _consume_subscription_direct(message, count=1)
            return static_reply, None

        # 🚫 3. صورة Spam / ليست روشتة طبية
        not_prescription_reply = (
            "عذراً، يبدو أن الصورة المرفقة ليست روشتة طبية واضحة. يرجى إرسال صورة روشتة صحيحة لطلب التحاليل."
        )
        ClientService.save_chat_exchange(
            platform_id=message.platform_id,
            page_id=message.page_id,
            sender_id=message.sender_id,
            user_message=message.text or "📷 [صورة غير واضحة]",
            bot_reply=not_prescription_reply,
        )
        _consume_subscription_direct(message, count=1)

        return (
            not_prescription_reply,
            None,
        )

    except Exception as e:
        print(f"[handle_image_message] Error: {e}")

        from notified_center.EmailSender import send_production_alert

        send_production_alert(
            subject="Image Processing Failure in message_processor",
            body_or_error=e,
            context={
                "sender_id": message.sender_id,
                "page_id": message.page_id,
                "platform_id": message.platform_id,
            },
        )

        return (
            "عذرًا، حدث خطأ أثناء معالجة الصورة المرفقة. يرجى المحاولة مرة أخرى.",
            None,
        )


def handle_multi_image_messages(image_messages: list, page, combined_text: str = "") -> tuple[str, bytes | None]:
    """معالجة عدة صور روشتات معاً وتوثيق حالة كل صورة بدقة من 1 إلى N."""
    total_images_count = len(image_messages)
    detailed_images_report = []
    has_any_success = False
    total_ocr_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    waha_handler = None

    for idx, msg in enumerate(image_messages, start=1):
        try:
            image_bytes = None

            # 1. WhatsApp
            if (msg.platform_name or "").lower() == "whatsapp" or getattr(msg, "platform_id", None) == 2:
                if not waha_handler:
                    from platforms.waha_handler import WahaHandler
                    waha_handler = WahaHandler(page)
                image_bytes = waha_handler.download_media(msg.media, "image")

            # 2. Facebook
            else:
                image_url = msg.media.get("url") if msg.media else None
                if image_url:
                    img_res = requests.get(image_url, timeout=30)
                    if img_res.status_code == 200:
                        image_bytes = img_res.content

            if not image_bytes:
                detailed_images_report.append(f"📄 الروشتة #{idx}: ❌ تعذر تحميل الصورة.")
                continue

            # حفظ الصورة
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            uploads_dir = os.path.join(project_dir, "static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            image_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}.jpg")

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            client_identifier = _get_client_identity(msg, page)

            # تشغيل OCR
            ocr_result = process_prescription_ocr(
                image_path=image_path,
                phone_number=client_identifier,
                comes_from=f"{msg.platform_name}:{msg.sender_id}:{msg.page_id}",
                laboratory_id=page.laboratory_id,
            )

            usage = ocr_result.get("ocr_usage")
            if usage:
                total_ocr_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_ocr_usage["output_tokens"] += usage.get("output_tokens", 0)
                total_ocr_usage["total_tokens"] += usage.get("total_tokens", 0)

            # ✅ 1. روشتة مقروءة بنجاح
            if ocr_result.get("success"):
                has_any_success = True
                extracted_tests = [t for t in (ocr_result.get("services_mentioned") or []) if t]
                tests_list = ", ".join(extracted_tests) if extracted_tests else ocr_result.get("extracted_text", "")
                detailed_images_report.append(
                    f"📄 الروشتة #{idx} (مقروءة بنجاح):\n"
                    f"   - التحاليل المطلوبة: {tests_list}"
                )

            # ⏳ 2. روشتة خطها غير واضح -> مراجعة الطبيب
            elif ocr_result.get("classified_as") == "prescription":
                detailed_images_report.append(
                    f"📄 الروشتة #{idx} (قيد مراجعة الطبيب):\n"
                    f"   - الحالة: تم تحويلها للطبيب المختص لمراجعة الخط وتحديد التحاليل."
                )

            # 🚫 3. صورة Spam / ليست روشتة
            else:
                detailed_images_report.append(
                    f"📄 الروشتة #{idx} (غير صالحة / ليست روشتة):\n"
                    f"   - الحالة: الصورة المرفقة ليست روشتة طبية صالحة."
                )

        except Exception as e:
            print(f"[Multi-OCR Error] image #{idx}: {e}")
            detailed_images_report.append(f"📄 الروشتة #{idx}: ❌ حدث خطأ أثناء قراءة الصورة.")

    # لو كل الصور سبام أو للدكتور
    if not has_any_success:
        static_reply = (
            "تم استلام صورك المرفقة:\n\n"
            + "\n\n".join(detailed_images_report)
            + "\n\nوسيقوم الطبيب المختص بمراجعة ما يلزم وإبلاغك بالتفاصيل فوراً."
        )

        last_msg = image_messages[-1]
        ClientService.save_chat_exchange(
            platform_id=last_msg.platform_id,
            page_id=last_msg.page_id,
            sender_id=last_msg.sender_id,
            user_message=last_msg.text or f"📷 [تم إرسال {total_images_count} صور]",
            bot_reply=static_reply,
            summary=f"User uploaded {total_images_count} images. Status: {detailed_images_report}",
        )
        count_request()
        _consume_subscription_direct(last_msg, count=total_images_count)
        return static_reply, None

    # تمرير التقرير الكامل للـ Agent
    full_report_text = "\n\n".join(detailed_images_report)
    user_notes_part = f"\n\nUser Notes: {combined_text}" if combined_text else ""

    last_msg = image_messages[-1]
    last_msg.text = (
        f"[تقرير الروشتات الطبية المرفقة - إجمالي {total_images_count} صور]\n\n"
        f"{full_report_text}{user_notes_part}\n\n"
        "تعليمات هامة للرد (يجب التحدث باللغة العربية المصرية حصراً):\n"
        f"1. اذكر كل روشتة من #1 إلى #{total_images_count} بدون تخطي أي رقم.\n"
        "2. للروشتات المقروءة: اذكر التحاليل وتحضيراتها.\n"
        "3. للروشتات قيد المراجعة: وضح تحويلها للطبيب.\n"
        "4. للصور غير الصالحة: وضح أنها ليست روشتة طبية صالحة.\n"
        "5. اعرض الإجمالي التقديري للتحاليل المقروءة فقط في الأسفل.\n"
        "6. اعرض حجز زيارة منزلية أو التوجه للفرع."
    )

    result_text, ticket = run_agent(last_msg, ocr_usage=total_ocr_usage)
    _consume_subscription_direct(last_msg, count=total_images_count)
    return result_text, ticket