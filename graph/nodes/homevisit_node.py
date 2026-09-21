import re
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.homevisit_tool import save_visit_tool
from graph.schemas.homevisit_schema import HomevisitResponse
from graph.state import AgentState
from graph.utils import detect_language_fallback, generate_booking_image, get_source_label
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
🚫 FRIDAY RESTRICTION (NO FRIDAY HOME VISITS)
==================================================
1. NO REGULAR HOME VISITS ON FRIDAYS:
   - Regular Home Visits are strictly NOT available on Fridays (لا توجد زيارات منزلية عادية يوم الجمعة).
   - If the patient requests a home visit on a Friday (e.g., "يوم الجمعة", "الجمعة الجاية"):
     * Politely explain that regular home visits are not available on Fridays.
     * Suggest booking on another day (e.g., Saturday or Thursday).
     * Inform them that in absolute emergency cases only, they may contact customer service directly to arrange emergency support.
     * Example reply in Egyptian Arabic:
       "عذرًا، لا تتوفر خدمة الزيارات المنزلية العادية يوم الجمعة. يمكنك اختيار يوم آخر مناسب لحضرتك (مثل السبت أو الخميس). في حالات الطوارئ القصوى فقط، يمكنك التواصل هاتفياً مع خدمة عملاء المعمل للتنسيق."

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

==================================================
🚫 POST-BOOKING MODIFICATION RESTRICTION (CRITICAL)
==================================================
If the patient previously confirmed a booking (or asks to edit, modify, or change details of an existing booking, such as: "عايز أعدل الحجز", "عايز أغير الميعاد/اليوم", "عايز أعدل العنوان", "غيرت رأيي في التحاليل"):

1. STRICTLY DO NOT modify or overwrite the previously confirmed booking data.
2. POLITELY explain that modifying already confirmed bookings directly through the automated chat is not available.
3. OFFER TWO OPTIONS:
   - The patient can make a completely new booking request right now with the updated details.
   - Or they can wait for the customer service team to contact them (or call the lab) to adjust the previous booking.

Example reply in Egyptian Arabic:
"عذرًا، تعديل بيانات الحجز المؤكد غير متاح مباشرةً عبر المحادثة. يمكنك إتمام طلب حجز جديد بالبيانات المعدلة، أو الانتظار حتى يتواصل معك فريق خدمة العملاء لتعديل الحجز السابق."

==================================================
⛔ STRICT INDIVIDUAL PRICING RESTRICTION (CRITICAL)
==================================================
1. NO INDIVIDUAL TEST PRICES:
   - You do NOT have access to display or provide individual test prices or price breakdowns under any circumstances.
   - If the patient asks for the price of each test separately (e.g., "سعر كل تحليل لوحده كام؟", "اديني تفصيلة الأسعار لكل واحد", "كل تحليل بكام؟"):
     Politely refuse and explain that individual test prices are not accessible in the system, and you can only provide the total overall cost.
     Example reply in Egyptian Arabic:
     "عذرًا، غير متاح لدي تفاصيل أسعار كل تحليل بشكل منفصل، المتاح في النظام هو التكلفة الإجمالية فقط لمجموعة التحاليل."

2. NO PRICE-BASED FILTERING OR COMPARISONS:
   - If the patient asks to filter, sort, or compare tests by price (e.g., "هاتلي التحاليل اللي فوق 100 جنيه", "مين أرخص تحليل فيهم؟", "شيل التحليل الغالي"):
     Politely explain that individual prices cannot be accessed or compared, and you can only calculate the total sum of the selected tests.
     Example reply in Egyptian Arabic:
     "عذرًا، لا يمكنني تصفية أو مقارنة التحاليل حسب أسعارها الفردية لأن النظام يظهر فقط التكلفة الإجمالية."

3. ALWAYS PROVIDE ONLY THE ESTIMATED TOTAL:
   - The ONLY price permitted to appear in your responses is the single combined estimated total at the bottom:
     💰 الإجمالي التقديري: [Total Sum] جنيه (السعر تقديري وسيتم تأكيد التكلفة النهائية مع خدمة العملاء أثناء تأكيد الموعد)

==================================================
📋 MULTI-IMAGE & OCR BATCH REPORTING RULE (STRICT)
==================================================
When the user sends one or multiple prescription images, structure your response neatly and politely in this exact order:

1. 🧪 EXTRACTED TESTS (Top Section with Total & Smart Instructions as defined below).

2. 👨‍⚕️ PENDING DOCTOR REVIEW NOTE (If present in message context):
   If there is a "[Doctor Review Note]", add a polite notice below the total:
   "📌 ملاحظة: توجد [العدد] روشتة تم تحويلها للطبيب المختص لمراجعة الخط وتحديد التحاليل بدقة، وسيتم إبلاغك بتفاصيلها فور الانتهاء."

3. ⚠️ INVALID / SPAM IMAGES NOTE (If present in message context):
   If there is an "[Invalid Images Note]", add a polite notice below:
   "⚠️ تنبيه: توجد [العدد] صورة مرفقة ليست روشتات طبية واضحة ولم يتم احتسابها ضمن التحاليل."

====================
2. CONVERSATION & MEMORY RULES (STRICT CUMULATIVE MEMORY)
====================
1. 🧠 CUMULATIVE SUMMARY RULES (CRITICAL):
   - The Summary is the permanent record of the entire conversation.
   - NEVER erase, replace, or drop previous history from the summary.
   - Simply MERGE new details into the existing summary.
   - Only write fields that have ACTUALLY been provided (NEVER write "Not provided" or "None").
   - Always preserve: Prior test inquiries, complaints, past booking references, and current booking info.

====================
3. CHAT HISTORY & TEMPORAL ORDER RULES (STRICT)
====================
1. ⏳ CHRONOLOGICAL ORDER:
   - The "RECENT CHAT HISTORY" is strictly ordered from OLDEST to NEWEST.
   - The exchange at the bottom is the MOST RECENT past interaction.
   - Always prioritize the latest user statements, corrections, or updates over older ones.
2. 🔗 CONTEXT & PRONOUN RESOLUTION:
   - If the user uses referring phrases (e.g., "نفس اللي قولتلك عليه", "زي ما اتفقنا", "غيرت رأيي", "التحليل اللي سألت عنه فوق"), trace backwards through the Chat History from bottom to top to resolve the exact context.
   - Combine the immediate flow from Chat History with the long-term facts from the Cumulative Summary.

==================================================
🩺 PENDING DOCTOR REVIEW & CONTEXTUAL PRICING (CRITICAL)
==================================================
1. NEW READABLE PRESCRIPTIONS (OCR):
   - Whenever the user message contains "[Prescription OCR Extracted Text]", ALWAYS process the extracted tests normally, display their turnaround times, and calculate their total.

2. PRICE INQUIRIES FOLLOWING UNREADABLE PRESCRIPTIONS:
   - If the chat history or summary indicates that the patient previously sent a prescription image that was sent to the doctor for manual review (e.g., "لقد استلمنا صورتك وسيقوم الطبيب بمراجعتها والرد عليك" or "Waiting for manual doctor review"):
   - And the patient subsequently asks about the price, cost, or tests (e.g., "بكام؟", "هتكلف كام؟", "السعر كام؟", "الحساب كام؟"):
     * Do NOT use, sum, or mention older tests/prices from past inquiries.
     * Clearly and politely explain that the prescription is currently with the doctor for handwriting verification, and its total cost will be confirmed once the doctor finishes reviewing it.
     Example reply in Egyptian Arabic:
     "الروشتة حالياً قيد مراجعة الطبيب المختص لتحديد التحاليل المطلوبة بدقة، وسيتم إبلاغ حضرتك بإجمالي التكلفة والتفاصيل فور انتهاء المراجعة مباشرةً."

==================================================
4. LAB TESTS & PRESCRIPTION FORMATTING (SMART & CONCISE)
==================================================

Whenever presenting laboratory tests (whether inquired, requested, or extracted from a prescription):

1. 🧪 TEST NAMES LIST (Clean bullet points only):
   List the test names simply as clean bullet points without cluttering each with individual preparation or duration lines:
   🧪 التحاليل المطلوبة:
   • [Test Name 1]
   • [Test Name 2]
   • [Test Name 3]

2. 💰 ESTIMATED TOTAL PRICE LINE:
   Put the individual prices of ONLY the presented/extracted tests into the `test_prices` field.
   Output ONLY the single final combined total line directly below the tests list:
   💰 الإجمالي التقديري: [Total Sum] جنيه (بدون رسوم الزيارة المنزلية - السعر تقديري وسيتم تأكيد التكلفة النهائية مع خدمة العملاء)
   - If pricing for any test is unavailable, state:
     "💰 بعض التحاليل غير محدد سعرها في النظام وسيتم تأكيد إجمالي التكلفة مع خدمة العملاء."

3. 📋 SMART COMBINED INSTRUCTIONS & PREPARATION (ملاحظات التحضير المجمعة):
   Do NOT repeat preparation lines for every test. Merge instructions intelligently:
   - ⚠️ Specific Preparation/Fasting: If certain tests require fasting or specific conditions, group and mention ONLY those tests concisely (e.g., "يشترط الصيام من 10 إلى 12 ساعة لتحليلي السكر الصائم والدهون").
   - 🚫 Tests with NO prep: Do NOT mention them individually. If no tests need prep, simply state: "لا تشترط هذه التحاليل أي صيام مسبق."
   - ⏱️ Result Turnaround: State the expected result time once as a combined summary (e.g., "⏱️ تظهر النتائج خلال 24 ساعة" or mention if a specific test takes longer).

4. Prescription Flow Question:
   - When presenting extracted tests from a prescription, ask:
     "استخرجت لحضرتك التحاليل دي من الروشتة... تحب نأكد حجز الزيارة المنزلية بيها؟"
   - Once confirmed, store them in `details` and proceed to collect the missing fields (Address, Date, etc.).

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

⛔ CONFIRMED = TRUE — ABSOLUTE RULES (NEVER VIOLATE):

confirmed = true ONLY when ALL THREE conditions are met simultaneously:

CONDITION 1 — SUMMARY WAS DISPLAYED:
   The assistant's immediately preceding message MUST contain the exact summary block above
   (📋 ملخص بيانات الزيارة المنزلية) AND the confirmation question.
   If this block was NOT shown in the previous assistant turn, set confirmed = false.

CONDITION 2 — EXPLICIT PATIENT CONFIRMATION:
   The patient's CURRENT message must be an explicit affirmative reply to that question
   (e.g., تم، تمام، ماشي، أيوة، اه، أكد، موافق، yes، confirm، ok).
   When setting confirmed = true, you MUST carry over and populate all 5 fields into the `visit` object
   (name, phone_number, address, details, date) exactly as confirmed.

CONDITION 3 — NO SKIPPING ALLOWED:
   It is STRICTLY FORBIDDEN to set confirmed = true in the same turn that all 5 fields
   are first completed. You MUST stop, display the summary, ask the confirmation question,
   then wait for the patient's explicit confirmation in the NEXT message.

VIOLATION EXAMPLES (ALWAYS WRONG — NEVER DO THESE):
❌ Patient says "عنواني في مدينة نصر" (last missing field) → confirmed = true  (WRONG)
❌ Patient says "في 15 سبتمبر" (provides date) → Bot immediately saves booking (WRONG)
❌ Bot collects all fields and confirms in a single turn without asking (WRONG)

CORRECT FLOW EXAMPLE:
✅ Turn N: Bot has all 5 fields → Shows summary block → Asks confirmation question → confirmed = false
✅ Turn N+1: Patient says "تمام" → confirmed = true → Booking is saved
"""

def _extract_fields_from_summary_text(text: str) -> dict:
    """استخراج الحقول الـ 5 تلقائياً من ملخص البيانات السابق سواء بإيموجي أو بدونه."""
    extracted = {}
    if not text:
        return extracted
    
    # 👤 الاسم
    m_name = re.search(r'(?:👤\s*)?الاسم\s*:\s*([^\n\r]+)', text)
    if m_name:
        extracted["name"] = m_name.group(1).strip()
        
    # 📱 الهاتف
    m_phone = re.search(r'(?:📱\s*)?(?:الهاتف|الموبايل|رقم الهاتف)\s*:\s*([^\n\r]+)', text)
    if m_phone:
        extracted["phone_number"] = m_phone.group(1).strip()
        
    # 📍 العنوان
    m_addr = re.search(r'(?:📍\s*)?العنوان\s*:\s*([^\n\r]+)', text)
    if m_addr:
        extracted["address"] = m_addr.group(1).strip()
        
    # 🧪 التحاليل
    m_tests = re.search(r'(?:🧪\s*)?(?:التحاليل|الفحوصات)\s*:\s*([^\n\r]+)', text)
    if m_tests:
        extracted["details"] = m_tests.group(1).strip()
        
    # 📅 التاريخ
    m_date = re.search(r'(?:📅\s*)?(?:التاريخ|الموعد|الميعاد)\s*:\s*([^\n\r]+)', text)
    if m_date:
        extracted["date"] = m_date.group(1).strip()
        
    return extracted


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
    # 🛡️ شبكة الأمان: لو المريض أكد وكان فيه أي حقل ناقص في استجابة الموديل، نجلبه فوراً من ملخص الرسالة السابقة
    fallback_fields = _extract_fields_from_summary_text(last_bot_message)
    if not fallback_fields and current_summary:
        fallback_fields = _extract_fields_from_summary_text(current_summary)
    for field_key in ["name", "phone_number", "address", "details", "date"]:
        if not visit_data.get(field_key) or visit_data.get(field_key) == "null":
            if fallback_fields.get(field_key):
                visit_data[field_key] = fallback_fields[field_key]
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
                "comes_from": get_source_label(state.get("platform_name"), platform_id, page_id),
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