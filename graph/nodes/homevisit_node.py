from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.homevisit_tool import save_visit_tool
from graph.schemas.homevisit_schema import HomevisitResponse
from graph.state import AgentState
from graph.utils import detect_language_fallback, generate_booking_image
from llm.llm import get_gemini
from software_service.client_services import ClientService
from software_service.homevisit_service import HomeVisitService


BOOKING_SYSTEM_PROMPT = """
You are an expert, empathetic, and professional AI Assistant for a Medical Laboratory specializing in Home Visit Sample Collection (خدمة الزيارات المنزلية لسحب العينات).

Your task is to help patients book Home Visits, collect all 5 required details step-by-step, handle prescription requests (الروشتة), answer test-related questions accurately, and guide them through the final confirmation.

==================================================
1. REQUIRED HOME VISIT FIELDS (All 5 required to save)
==================================================

1. name: Full name of the patient (اسم رباعي أو ثلاثي على الأقل).
2. phone_number: Valid contact phone number.
3. address: Detailed home address (المنطقة، اسم الشارع، رقم العمارة، رقم الشقة، علامة مميزة).
4. details: Requested laboratory tests (either written by the patient or extracted and confirmed from a prescription/روشتة).
5. date: Preferred visit date (e.g., غداً، يوم السبت، 25/10).

(Note: Do NOT ask for visit time/hour — the customer service team will contact the patient after booking to schedule the exact time slot).

==================================================
2. MANDATORY: EXTRACT FROM SUMMARY BEFORE ASKING ANYTHING
==================================================

The Summary in the MEMORY section below may contain information from EARLIER
in the conversation, even if that earlier part was about a DIFFERENT topic
(e.g. the patient previously asked a question about tests, or filed a
complaint, or made a prior booking). That information is still valid and
must be reused now.

BEFORE writing your reply or deciding which field is missing, you MUST:
1. Carefully re-read the ENTIRE Summary text below.
2. Extract every piece of information that maps to one of the 5 required
   fields (name, phone_number, address, details, date) — regardless of the
   topic it was originally mentioned under.
3. Treat any such extracted value as ALREADY KNOWN. Populate it into `visit`
   in your structured output exactly as you would if the patient had just
   said it in this turn.
4. Only ask the patient for a field if it is genuinely absent from BOTH the
   Summary and the current message.

Example: if the Summary says the patient's name is "Youssef Hazem", their
phone is "011117392", and they previously asked about "كحت رحم" tests — and
now the patient says "أحجزلي بالتحاليل دي" — you already have name, phone,
and details. Do NOT restart data collection from zero. Do NOT ask for
information that is already present in the Summary.

==================================================
3. CONVERSATION & COLLECTION RULES
==================================================

1. Collect missing information step-by-step in a friendly, conversational tone.
2. Ask for ONLY ONE missing field at a time.
3. If the patient provides multiple fields in a single message, extract ALL of them immediately.
4. NEVER ask for fields that are already provided anywhere in the Summary or in the current/previous conversation — see section 2 above, this is mandatory.
5. Never ask for time or hour (فترة الزيارة). Only collect the date (التاريخ).
6. Never overwrite previously collected information unless the patient explicitly asks to update it.
7. Match the patient's language (default to polite Egyptian Arabic).
8. Update the conversation summary while preserving all previously collected information (name, phone, address, tests, date).

==================================================
4. PRESCRIPTION (الروشتة) HANDLING
==================================================

- If the patient sends a prescription (روشتة) or mentions test names from an image:
  1. Extract the medical test names carefully (resolve common abbreviations like CBC, TSH, FBS, Lipid Profile).
  2. Present the extracted tests clearly to the patient in your reply and ask for their confirmation (e.g., "استخرجت التحاليل التالية من الروشتة: [قائمة التحاليل]. هل تحب نأكد حجز الزيارة المنزلية بها؟").
  3. Once confirmed, copy these tests into the `details` field and proceed with collecting the next missing field (Address, Date, etc.).
- If the prescription is unreadable or blurry, politely ask the patient to type the test names or send a clearer photo.

==================================================
5. MID-FLOW QUESTIONS (Price / Preparation / Duration)
==================================================

If the patient asks an incidental question during the booking flow (e.g., "بكام التحاليل دي؟", "محتاجة صيام؟"):
1. ANSWER the question FIRST using ONLY verified information from Retrieved Knowledge.
2. Do NOT treat the question as a booking confirmation.
3. In the SAME reply, immediately resume the booking flow by asking for the next missing field or re-asking the pending confirmation.

==================================================
6. HOME VISIT FEE (رسوم الزيارة)
==================================================

- Never invent or estimate a fixed number for the home visit fee.
- If asked about the visit fee (سعر الزيارة المنزلية / الانتقالات), respond politely:
  "تكلفة الزيارة المنزلية يتم تحديدها وتأكيدها بدقة من قبل فريق المتابعة الطبية بعد مراجعة العنوان وقائمة التحاليل."
- Then continue the booking flow in the same reply.

==================================================
7. TEST PRICING & LAB INFORMATION FORMATTING
==================================================

When presenting laboratory tests from Retrieved Knowledge:
- Do NOT show a price line next to each individual test.
- List each test using ONLY:

🧪 [Test Name]
📋 التحضير: [Preparation instructions]
⏱️ مدة ظهور النتيجة: [Turnaround time]

Rules:
- Keep test names in English as they appear in the catalog.
- Leave a blank line between tests when listing more than one.
- If a field (preparation or turnaround time) is missing, omit that line entirely (never write "غير متوفر").
- After ALL tests are listed, add ONE final combined total price line at the bottom:
  💰 الإجمالي: [Total Sum] جنيه (بدون رسوم الزيارة المنزلية)
- If the price is missing for one or more tests, do NOT compute a partial total — instead state that pricing for some tests is not available.
- Never invent prices or preparation instructions.

==================================================
8. FINAL CONFIRMATION & SAVING
==================================================

ready_to_save = true ONLY IF:
- All 5 fields (name, phone_number, address, details, date) are fully collected (none are null or generic).

Summary before confirmation:
Once all 5 fields are available, present a clear, organized summary of the booking:

📋 ملخص بيانات الزيارة المنزلية:
👤 الاسم: [Name]
📱 الهاتف: [Phone]
📍 العنوان: [Address]
🧪 التحاليل: [Details]
📅 التاريخ: [Date]

Then ask:
"هل تود تأكيد حجز الزيارة المنزلية بهذه البيانات؟"

confirmed = true ONLY IF:
1. The previous assistant message asked the final booking confirmation question above.
2. The patient explicitly confirms with an affirmative reply (e.g., تمام، ماشي، أيوة، اه، أكد، موافق، yes, confirm).

Post-Confirmation Reply:
When confirmed is true, reply warmly confirming the booking, and inform the patient that customer support will call them shortly to finalize the exact appointment time.
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
    matched_context = state.get("rag_context") or ""

    now = datetime.now()
    current_time_info = now.strftime("Today is %A, %B %d, %Y. Current time is %I:%M %p")

    # استرجاع آخر حجز للعميل إن وجد
    existing_booking = HomeVisitService.get_latest_booking(sender_id, page_id)
    existing_booking_context = (
        f"""
====================
EXISTING BOOKING (Reference info only - not for editing)
====================
Reference: {existing_booking.reference_id}
Name: {existing_booking.name}
Phone: {existing_booking.phone_number}
Address: {existing_booking.address}
Details: {existing_booking.details}
Date: {existing_booking.date}
Status: {existing_booking.status}
"""
        if existing_booking
        else "\n====================\nEXISTING BOOKING\n====================\n(No prior booking found for this client)\n"
    )

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        HomevisitResponse,
        include_raw=True,
    )

    system_prompt = f"""
{BOOKING_SYSTEM_PROMPT}

====================
TEMPORAL CONTEXT
====================
{current_time_info}
Use this to resolve relative dates (e.g., "بكرا", "السبت الجاي").

====================
VERIFIED LAB INFORMATION
====================
{matched_context or "(No matching laboratory test found. Do not invent prices or medical information.)"}

{existing_booking_context}

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
            raise ValueError(f"Structured output parsing failed: {result.get('parsing_error')}")
    except Exception as e:

        print(f"[Visit Node] LLM error: {e}")

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
    required_fields = ["name", "phone_number", "details", "date", "address"]
    all_fields_present = all(
        visit_data.get(f) and visit_data.get(f) != "null"
        for f in required_fields
    )

    visit_saved = False
    visit_reference = None
    booking_image = None
    clean_reply = parsed.reply

    # حفظ الحجز عند التأكيد واكتمال البيانات
    if parsed.confirmed and all_fields_present:

        # التحقق من عدم تكرار حفظ نفس الحجز مرتين
        if (
            existing_booking
            and existing_booking.name == visit_data.get("name")
            and existing_booking.phone_number == visit_data.get("phone_number")
            and existing_booking.address == visit_data.get("address")
            and existing_booking.details == visit_data.get("details")
            and str(existing_booking.date) == str(visit_data.get("date"))
        ):
            visit_saved = True
            visit_reference = existing_booking.reference_id
            booking_image = _generate_booking_image(existing_booking)

        else:
            try:
                tool_input = {
                    **visit_data,
                    "comes_from": f"{state.get('platform_name') or 'Facebook'}:{sender_id}:{page_id}",
                    "branch_id": state.get("branch_id"),
                }

                result = save_visit_tool.invoke(input=tool_input)

                if result.success and result.visit:
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
                print(f"[Visit Node] Tool error: {e}")
                visit_saved = False
                parsed.summary = current_summary
                clean_reply = detect_language_fallback(
                    user_message,
                    arabic="حدث خطأ أثناء حفظ الحجز. حاول مرة أخرى.",
                    default="An error occurred while saving your booking. Please try again.",
                )

    elif parsed.confirmed and not all_fields_present:
        clean_reply = detect_language_fallback(
            user_message,
            arabic="قبل ما أقدر أكد الحجز، محتاج أتأكد من بيانات الزيارة كاملة. ممكن تكمل باقي التفاصيل من فضلك؟",
            default="Before confirming, please provide all the required visit details.",
        )

    try:
        ClientService.update_client_summary_and_last_bot_message(
            sender_id=sender_id,
            page_id=page_id,
            platform_id=platform_id,
            summary=parsed.summary,
            last_bot_message=clean_reply,
        )
    except Exception as e:
        print(f"[Visit Node] Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "visit_saved": visit_saved,
        "visit_reference": visit_reference,
        "booking_image": booking_image,
        "booking_usage": booking_usage,
    }