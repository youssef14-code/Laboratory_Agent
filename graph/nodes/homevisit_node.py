import re
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.homevisit_tool import save_visit_tool
from graph.schemas.homevisit_schema import HomevisitResponse
from graph.state import AgentState
from graph.utils import detect_language_fallback, generate_booking_image
from llm.llm import get_gemini
from software_service.client_services import ClientService


BOOKING_SYSTEM_PROMPT = """
You are a helpful, empathetic, and professional AI Assistant for a Medical Laboratory specializing in Home Visit Sample Collection (خدمة الزيارات المنزلية لسحب العينات).

Your task is to guide patients step-by-step to book Home Visits, extract prescription tests, answer questions accurately, and guide them through final confirmation.

====================
1. REQUIRED BOOKING FIELDS (All 5 required)
====================

1. name: Patient full name (as provided).
2. phone_number: Contact phone number digits.
3. address: Patient address as provided (accept whatever address the user mentions as-is).
4. details: Requested laboratory test names.
5. date: Preferred visit date (e.g., YYYY-MM-DD or as stated).

(Note: NEVER ask for visit time/hour — customer service contacts the patient to schedule the exact time slot).

==================================================
IN-BRANCH BOOKING REQUESTS
==================================================

This assistant handles HOME VISIT bookings only.

If the patient asks to book an appointment inside a laboratory branch
(حجز داخل الفرع / حجز في المعمل / هاجي الفرع / أحجز في فرع معين):

- Do NOT collect booking details.
- Do NOT set `confirmed = true`.
- Do NOT call the home-visit booking tool.
- Politely explain in the patient's language that this booking flow is only
  for home visits.

In Egyptian Arabic, reply naturally with:
"خدمة الحجز المتاحة هنا خاصة بالزيارات المنزلية فقط لسحب العينات من المنزل. تقدر تتوجه لأقرب فرع مباشرةً لإجراء التحاليل."

If the patient wants a home visit instead, continue the normal home-visit
booking flow.

====================
2. CONVERSATION & MEMORY RULES (STRICT CUMULATIVE MEMORY)
====================
1. 🧠 CUMULATIVE SUMMARY RULES (CRITICAL):
   - The Summary is the permanent record of the entire conversation.
   - NEVER erase, replace, or drop previous history from the summary.
   - Simply MERGE new details into the existing summary.
   - Only write fields that have ACTUALLY been provided (NEVER write "Not provided" or "None").
   - Always preserve: Prior test inquiries, complaints, past booking references, and current booking info.
   Example progression:
   Turn 1 Summary: User greeted and inquired about CBC (100 EGP).
   Turn 2 (User says "عايز احجز واسمي يوسف"): User inquired about CBC. Patient: Youssef. Booking in progress.
   Turn 3 (User provides phone and date): User inquired about CBC. Patient: Youssef (01112256357). Preferred date: 2026-09-05. Booking in progress.

====================
3.CHAT HISTORY & TEMPORAL ORDER RULES (STRICT)
====================
1. ⏳ CHRONOLOGICAL ORDER:
   - The "RECENT CHAT HISTORY" is strictly ordered from OLDEST to NEWEST.
   - The exchange at the bottom is the MOST RECENT past interaction.
   - Always prioritize the latest user statements, corrections, or updates over older ones.
2. 🔗 CONTEXT & PRONOUN RESOLUTION:
   - If the user uses referring phrases (e.g., "نفس اللي قولتلك عليه", "زي ما اتفقنا", "غيرت رأيي", "التحليل اللي سألت عنه فوق"), trace backwards through the Chat History from bottom to top to resolve the exact context.
   - Combine the immediate flow from Chat History with the long-term facts from the Cumulative Summary.
      
====================
4. LAB TESTS & PRESCRIPTION FORMATTING (STRICT RULES)
====================

Whenever presenting laboratory tests (whether inquired, requested, or extracted from a prescription):

1. Format EACH test block EXACTLY like this:

🧪 [Test Name]
📋 التحضير: [Preparation instructions]
⏱️ مدة ظهور النتيجة: [Result turnaround time]

2. ⛔ STRICT PRICING & TOTAL SUM RULES:
- NEVER write a price line (like "💰 السعر" or "💰 Price") directly under any individual test block.
- Put the individual prices of ONLY the presented/extracted tests into the `test_prices` field.
- Output ONLY the single final TOTAL line at the bottom:
  💰 الإجمالي: [Total Sum] جنيه (بدون رسوم الزيارة المنزلية)
- If pricing for any test is unavailable, state:
  "💰 بعض التحاليل غير محدد سعرها في النظام وسيتم تأكيد إجمالي التكلفة مع خدمة العملاء."

3. Prescription Flow:
- When extracting tests from a prescription, list tests in the exact format above and ask:
  "استخرجت لحضرتك التحاليل دي من الروشتة... تحب نأكد حجز الزيارة المنزلية بيها؟"
- Once confirmed, store them in `details` and ask for the next missing field (Address, Date, etc.).
- If unreadable, politely ask the patient to type the test names or send a clearer photo.

====================
5. FINAL CONFIRMATION
====================

Summary before confirmation:
When all 5 fields (name, phone, address, details, date) are collected, present:

📋 ملخص بيانات الزيارة المنزلية:
👤 الاسم: [Name]
📱 الهاتف: [Phone]
📍 العنوان: [Address]
🧪 التحاليل: [Details]
📅 التاريخ: [Date]

Then ask:
"هل تود تأكيد حجز الزيارة المنزلية بهذه البيانات؟"

confirmed = true ONLY IF:
1. The previous assistant message asked the final confirmation question above.
2. The patient explicitly confirms with an affirmative reply (e.g., تم، تمام، ماشي، أيوة، اه، أكد، موافق، yes, confirm, ok).
"""


def _generate_booking_image(visit) -> bytes | None:
    """يولد تذكرة الحجز ولا يوقف مسار التنفيذ في حال حدوث خطأ."""
    print(f"[DEBUG] _generate_booking_image called for visit={visit.reference_id}")
    try:
        img = generate_booking_image(
            name=visit.name,
            phone=visit.phone_number,
            date=str(visit.date or ""),
            details=visit.details or "",
            reference_id=visit.reference_id,
            address=visit.address or "",
        )
        print(f"[DEBUG] _generate_booking_image SUCCESS, bytes={len(img) if img else 0}")
        return img
    except Exception as e:
        print(f"[Visit Node] PDF generation error: {e}")
        import traceback
        traceback.print_exc()
        return None


def visit_node(state: AgentState) -> dict:
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")
    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""
    rag_context = state.get("rag_context") or ""
    now = datetime.now()
    current_time_info = now.strftime("Today is %A, %B %d, %Y. Current time is %I:%M %p")

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        HomevisitResponse,
        method="json_schema",
        include_raw=True,
    )

    system_prompt = f"""
{BOOKING_SYSTEM_PROMPT}

====================
TEMPORAL CONTEXT
====================
{current_time_info}

====================
RETRIEVED KNOWLEDGE
====================
{rag_context or "(No relevant laboratory information was retrieved.)"}


====================
RECENT CHAT HISTORY (Last Exchanges)
====================
{chat_history or "(No previous chat history)"}

====================
MEMORY
====================

Summary:
{current_summary}

Last Bot Message:
{last_bot_message}
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    try:
        result = structured_llm.invoke(messages)
        parsed: HomevisitResponse = result["parsed"]
        raw_response = result["raw"]

        if parsed is None:
            raise ValueError(f"Homevisit parsing failed: {result.get('parsing_error')}")

    except Exception as e:
        print(f"[Visit Node] ❌ LLM error | sender_id={sender_id} | error={e}")
        fallback = detect_language_fallback(
            user_message,
            arabic="عذرًا، حدث خطأ مؤقت أثناء معالجة الحجز. حاول مرة أخرى.",
            default="Sorry, a temporary error occurred while processing your booking. Please try again.",
        )
        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "visit_saved": False,
            "visit_reference": None,
            "booking_image": None,
            "booking_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)
    booking_usage = (
        {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if usage
        else None
    )

    visit_data = parsed.visit.model_dump(exclude_none=True)


    # 🧹 فلترة العنوان لضمان استخراج المكان الصافي بدون أي نصوص زائدة
    if visit_data.get("address"):
        addr = str(visit_data["address"])
        addr = re.split(r'(?:\.|\n)?\s*(?:Date|التاريخ|Booking|Status|Tests|التحاليل|Phone|الهاتف):', addr, flags=re.IGNORECASE)[0].strip()
        sentences = [s.strip() for s in addr.split('.') if s.strip()]
        visit_data["address"] = sentences[0] if sentences else addr

    required_fields = ["name", "phone_number", "address", "details", "date"]
    
    all_fields_present = all(
        visit_data.get(f) and visit_data.get(f) != "null"
        for f in required_fields
    )

    visit_saved = False
    visit_reference = None
    booking_image = None
    clean_reply = parsed.reply

    if parsed.test_prices:
        exact_total = int(sum(parsed.test_prices))
        if "💰 الإجمالي:" in clean_reply or "الإجمالي:" in clean_reply:
            clean_reply = re.sub(
                r'💰?\s*الإجمالي\s*:.*',
                f'💰 الإجمالي: {exact_total} جنيه (بدون رسوم الزيارة المنزلية)',
                clean_reply,
            )

    

    decision_path = "collecting_fields"

    # حفظ الحجز عند التأكيد واكتمال البيانات الـ 5
    if parsed.confirmed and all_fields_present:
        try:
            tool_input = {
                "name": visit_data["name"],
                "phone_number": visit_data["phone_number"],
                "address": visit_data["address"],
                "details": visit_data["details"],
                "date": str(visit_data["date"]),
                "comes_from": f"{state.get('platform_name') or 'Facebook'}:{sender_id}:{page_id}",
            }

            result = save_visit_tool.invoke(input=tool_input)

            if result.success and result.visit:
                decision_path = "new_save_success"
                visit_saved = True
                visit_reference = result.visit.reference_id
                booking_image = _generate_booking_image(result.visit)

                clean_reply = detect_language_fallback(
                    user_message,
                    arabic=(
                        f"تم تأكيد حجزك بنجاح ✅\n"
                        f"رقم الطلب: *{visit_reference}*\n\n"
                        f"هيتم التواصل معاك من فريق خدمة العملاء لتأكيد المعاد نهائيًا.\n"
                        f"وده تذكرة الحجز 🎫"
                    ),
                    default=(
                        f"Your booking has been confirmed ✅\n"
                        f"Reference: *{visit_reference}*\n\n"
                        f"Our customer service team will contact you to confirm the appointment.\n"
                        f"Here's your booking ticket 🎫"
                    ),
                )
            else:
                raise ValueError(result.message)

        except Exception as e:
            decision_path = "save_tool_error"
            print(f"[Visit Node] ❌ save_visit_tool error: {e}")
            visit_saved = False
            clean_reply = detect_language_fallback(
                user_message,
                arabic="حدث خطأ أثناء حفظ الحجز. حاول مرة أخرى.",
                default="An error occurred while saving your booking. Please try again.",
            )

    elif parsed.confirmed and not all_fields_present:
        decision_path = "confirmed_but_incomplete"
        clean_reply = detect_language_fallback(
            user_message,
            arabic="قبل ما أقدر أكد الحجز، محتاج أتأكد من بيانات الزيارة كاملة. ممكن تكمل باقي التفاصيل من فضلك؟",
            default="Before confirming, please provide all the required visit details.",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 📊 LOGGING: طباعة حالة الحقول ومسار الحجز والتوكنز
    # ══════════════════════════════════════════════════════════════════════════
    def _status_icon(val):
        return f"✅ '{val}'" if (val and val != "null") else "❌ (Missing)"

    print("\n" + "─" * 65)
    print(f"🏥 [Visit Node] Booking Progress | Sender: {sender_id}")
    print("─" * 65)
    print(f"  👤 Name     : {_status_icon(visit_data.get('name'))}")
    print(f"  📱 Phone    : {_status_icon(visit_data.get('phone_number'))}")
    print(f"  📍 Address  : {_status_icon(visit_data.get('address'))}")
    print(f"  🧪 Details  : {_status_icon(visit_data.get('details'))}")
    print(f"  📅 Date     : {_status_icon(visit_data.get('date'))}")
    print("─" * 65)
    print(f"  🔍 Status   : {'✅ Ready (5/5)' if all_fields_present else '❌ Incomplete'} | Confirmed: {parsed.confirmed} | Path: {decision_path}")
    if booking_usage:
        print(f"  📊 Tokens   : In={booking_usage['input_tokens']} | Out={booking_usage['output_tokens']} | Total={booking_usage['total_tokens']}")
    if visit_saved:
        print(f"  🎉 Saved Successfully : ✅ Reference: {visit_reference}")
    print("─" * 65 + "\n")

    try:
        ClientService.save_chat_exchange(
            platform_id=platform_id,
            page_id=page_id,
            sender_id=sender_id,
            user_message=user_message,
            bot_reply=clean_reply,
            summary=parsed.summary,
        )
    except Exception as e:
        print(f"[Visit Node] ⚠️ Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "visit_saved": visit_saved,
        "visit_reference": visit_reference,
        "booking_image": booking_image,
        "booking_pdf": booking_image,    # 👈
        "booking_usage": booking_usage,
    }