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
    ):
        self.sender_id = sender_id
        self.page_id = page_id
        self.platform_id = platform_id
        self.platform_name = platform_name
        self.type = msg_type
        self.text = text
        self.media = media


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


def run_agent(message: IncomingMessage, ocr_usage: dict = None) -> tuple[str, bytes | None]:

    # 1. استخراج كائن العميل بأمان من الـ Tuple
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
    # 2. تجهيز الـ State الموحدة
    state = {
        "page_id": str(message.page_id),
        "sender_id": str(message.sender_id),
        "platform_id": message.platform_id,
        "platform_name": platform_name,
        "user_message": message.text or "",
        "summary": current_summary,
        "last_bot_message": current_last_bot,
        "chat_history": formatted_chat_history,  # 👈 تمرير سجل المحادثة إلى Graph State

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
    """معالجة صور الروشتات واستخراج التحاليل عبر الـ OCR."""
    image_bytes = None

    try:
        # WhatsApp
        if (message.platform_name or "").lower() == "whatsapp":
            from platforms.waha_handler import WahaHandler

            handler = WahaHandler(page)
            image_bytes = handler.download_media(message.media, "image")

            if not image_bytes:
                return "عذرًا، فشل تحميل الصورة المرفقة. يرجى المحاولة مرة أخرى.", None

        # Facebook / Messenger
        else:
            image_url = message.media.get("url") if message.media else None

            if not image_url:
                return "برجاء إرسال صورة روشتة صالحة.", None

            print(f"[handle_image_message] Downloading image: {image_url}")

            img_res = requests.get(image_url, timeout=30)

            if img_res.status_code != 200:
                return "عذرًا، فشل تحميل الصورة المرفقة. يرجى المحاولة مرة أخرى.", None

            image_bytes = img_res.content

        # Save image
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        uploads_dir = os.path.join(project_dir, "static", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.jpg"
        image_path = os.path.join(uploads_dir, filename)

        with open(image_path, "wb") as f:
            f.write(image_bytes)

        # OCR
        ocr_result = process_prescription_ocr(
            image_path=image_path,
            phone_number="",
            comes_from=f"{message.platform_name}:{message.sender_id}:{message.page_id}",
            laboratory_id=page.laboratory_id,
        )

        ocr_usage = ocr_result.get("ocr_usage")

        if ocr_result.get("success"):
            extracted_text = ocr_result.get("extracted_text", "")
            message.text = f"[Prescription OCR Extracted Text]:\n{extracted_text}"
            return run_agent(message, ocr_usage=ocr_usage)

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
            return static_reply, None

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
    """معالجة عدة صور روشتات معاً بذكاء وفصل الروشتات المقروءة عن التي تحتاج مراجعة الطبيب."""
    all_extracted_texts = []
    unreadable_prescriptions_count = 0
    total_ocr_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    for idx, msg in enumerate(image_messages):
        try:
            image_url = msg.media.get("url") if msg.media else None
            if not image_url:
                continue

            img_res = requests.get(image_url, timeout=30)
            if img_res.status_code != 200:
                continue

            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            uploads_dir = os.path.join(project_dir, "static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            image_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}.jpg")

            with open(image_path, "wb") as f:
                f.write(img_res.content)

            # تشغيل OCR على كل صورة
            ocr_result = process_prescription_ocr(
                image_path=image_path,
                phone_number="",
                comes_from=f"{msg.platform_name}:{msg.sender_id}:{msg.page_id}",
                laboratory_id=page.laboratory_id,
            )

            # تجميع استهلاك الـ OCR
            usage = ocr_result.get("ocr_usage")
            if usage:
                total_ocr_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_ocr_usage["output_tokens"] += usage.get("output_tokens", 0)
                total_ocr_usage["total_tokens"] += usage.get("total_tokens", 0)

            # ✅ 1. الروشتة الناجحة فقط (ثقة 90% فأكثر)
            if ocr_result.get("success"):
                extracted = ocr_result.get("extracted_text", "")
                all_extracted_texts.append(f"--- [Prescription Image #{idx+1} - Confirmed] ---\n{extracted}")

            # ⏳ 2. الروشتة غير الواضحة (ثقة منخفضة) -> مراجعة الطبيب
            elif ocr_result.get("classified_as") == "prescription":
                unreadable_prescriptions_count += 1

        except Exception as e:
            print(f"[Multi-OCR Error] image #{idx+1}: {e}")

    # 🎯 الحالة الأولى: كل الروشتات المرفقة تحتاج مراجعة الطبيب (لم تنجح أي واحدة بنسبة 90%)
    if not all_extracted_texts and unreadable_prescriptions_count > 0:
        static_reply = "لقد استلمنا صورتك وسيقوم الطبيب بمراجعتها والرد عليك."
        last_msg = image_messages[-1]
        ClientService.save_chat_exchange(
            platform_id=last_msg.platform_id,
            page_id=last_msg.page_id,
            sender_id=last_msg.sender_id,
            user_message=last_msg.text or "📷 [تم إرسال صورة روشتة طبية]",
            bot_reply=static_reply,
            summary="User uploaded a prescription image. Waiting for manual doctor review on dashboard.",
        )
        count_request()
        return static_reply, None

    # 🎯 الحالة الثانية: توجد روشتة واحدة على الأقل واضحة وناجحة (90%+)
    if all_extracted_texts:
        merged_ocr = "\n\n".join(all_extracted_texts)
        if unreadable_prescriptions_count > 0:
            merged_ocr += f"\n\n[Doctor Review Note]: ({unreadable_prescriptions_count} other uploaded prescription image(s) had unclear handwriting and was sent to the doctor for manual review. Inform the patient politely.)"

        last_msg = image_messages[-1]
        last_msg.text = f"[Prescription OCR Extracted Text]:\n{merged_ocr}\n\nUser Notes: {combined_text}"
        return run_agent(last_msg, ocr_usage=total_ocr_usage)

    # 🎯 الحالة الثالثة: الصور المرفقة ليست روشتات طبية
    not_presc_reply = "عذراً، يبدو أن الصور المرفقة ليست روشتات طبية واضحة. يرجى إرسال صورة روشتة صحيحة لطلب التحاليل."
    last_msg = image_messages[-1]
    ClientService.save_chat_exchange(
        platform_id=last_msg.platform_id,
        page_id=last_msg.page_id,
        sender_id=last_msg.sender_id,
        user_message=last_msg.text or "📷 [صورة غير واضحة]",
        bot_reply=not_presc_reply,
    )
    return not_presc_reply, None