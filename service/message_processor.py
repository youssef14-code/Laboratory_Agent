import os
import uuid
from pymupdf import message
import requests
import time
from graph.agent_response import AgentResponse
from graph.graph import get_agent_graph
from graph.utils import count_request
from ocr.processor import process_prescription_ocr
from software_service.client_services import ClientService
import logging
logger = logging.getLogger(__name__)

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
        sender_name=None,     # 👈 إضافة هذا الحقل
    ):
        self.sender_id = sender_id
        self.page_id = page_id
        self.platform_id = platform_id
        self.platform_name = platform_name
        self.type = msg_type
        self.text = text
        self.media = media
        self.sender_name = sender_name # 👈 حفظ الاسم


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


def _get_client_identity(message: IncomingMessage, page) -> str:
    """جلب رقم الهاتف أو اسم العميل بدقة."""
    platform = (message.platform_name or "").lower()

    # 🟢 واتساب
    if platform == "whatsapp" or getattr(message, "platform_id", None) == 2:
        sender = str(message.sender_id or "")
        sender_name = getattr(message, "sender_name", None)

        # 1. إذا وصل الاسم من الـ Webhook
        if sender_name and str(sender_name).strip() and str(sender_name).strip().lower() not in ["none", "null", ""]:
            return str(sender_name).strip()

        # 2. إذا كان الرقم صريحاً
        if "@c.us" in sender or "@s.whatsapp.net" in sender:
            num = sender.split("@")[0]
            if num.startswith("201") or len(num) >= 11:
                return num

        # 3. محاولة جلب الاسم مباشرة من كونتينر WAHA (waha1 أو waha)
        for host in ["http://waha1:3000", "http://waha:3000", "http://localhost:3000"]:
            try:
                url = f"{host}/api/contacts/{sender}?session=default"
                res = requests.get(url, timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    name = data.get("pushname") or data.get("name")
                    if name:
                        print(f"👉 [DIRECT WAHA FETCH SUCCESS] name={name}")
                        return str(name).strip()
            except Exception:
                continue

        return "واتساب"

    # 🔵 فيسبوك
    elif platform in ["facebook", "messenger"] or getattr(message, "platform_id", None) == 1:
        try:
            url = f"https://graph.facebook.com/v19.0/{message.sender_id}"
            res = requests.get(
                url,
                params={"fields": "name,first_name,last_name", "access_token": page.token},
                timeout=4,
            )
            if res.status_code == 200:
                data = res.json()
                name = data.get("name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
                if name:
                    return f"{name}"
        except Exception as e:
            print(f"[Facebook Name Fetch Error]: {e}")

    return getattr(message, "sender_name", None) or "عميل"


def _consume_subscription(message: "IncomingMessage", usage: dict) -> None:
    """خصم استهلاك الرسالة من باقة المختبر."""
    try:
        try:
            from software_service.subscripition_service import SubscriptionService
        except ImportError:
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
                "[OCR Extracted Tests prescription image]\n"
                f"{tests_list}\n\n"
                "Please provide full details, preparations needed, and prices for these tests."
            )
            logger.info("[handle_image_message] : %s", tests_list)
            result_text, ticket = run_agent(message, ocr_usage=ocr_usage)
            _consume_subscription_direct(message, count=1)  # +1 للـ OCR
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

            # حفظ الصورةOCR successful. Extracted tests
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
        f"[MULTI-PRESCRIPTION IMAGES REPORT - TOTAL {total_images_count} IMAGES]\n\n"
        f"{full_report_text}{user_notes_part}\n\n"
        "MANDATORY INSTRUCTIONS FOR AGENT:\n"
        f"1. You MUST list EVERY image from #1 to #{total_images_count} without skipping any number!\n"
        "2. For readable prescriptions: list their tests and preparation.\n"
        "3. For doctor review prescriptions: write clearly that it was forwarded to the doctor for review.\n"
        "4. For invalid/spam images: you MUST explicitly write that this image is not a valid medical prescription.\n"
        "5. Provide the combined total ONLY for the readable tests at the bottom.\n"
        "6. Ask about home visit or branch visit."
    )

    result_text, ticket = run_agent(last_msg, ocr_usage=total_ocr_usage)
    _consume_subscription_direct(last_msg, count=total_images_count)
    return result_text, ticket