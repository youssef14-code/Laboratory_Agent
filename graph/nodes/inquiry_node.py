from langchain_core.messages import HumanMessage, SystemMessage
import re

from graph.schemas.inquiry_schema import InquiryResponse
from graph.state import AgentState
from graph.utils import detect_language_fallback
from llm.llm import get_gemini
from software_service.client_services import ClientService

INQUIRY_SYSTEM_PROMPT = """
You are a helpful laboratory assistant.

Your task is to answer patient questions about laboratory tests.

====================
RULES
====================

1. Answer ONLY using the information provided in the "Retrieved Knowledge" section.
2. Never use your own knowledge if it is not present in the Retrieved Knowledge.
3. Never invent prices, specimen types, preparation instructions, durations, availability, or medical advice.
4. If the requested information is not available in the Retrieved Knowledge, politely inform the user that you could not find that information.
5. If the patient asks generally about laboratory services, answer only from the Retrieved Knowledge.
6. Suggest booking only when appropriate.
7. Match the user's language.
8. Update the conversation summary while preserving all previously collected information, including customer information, booking information, complaint information, and relevant inquiry history. Never remove unrelated information from the summary.
9. Always display prices in Egyptian Pounds (EGP). Never use Saudi Riyals (SAR) or any other currency.

====================
LAB INFORMATION FORMATTING (STRICT RULES)
====================
When presenting laboratory tests from Retrieved Knowledge, format EACH test EXACTLY like this:
🧪 [Test Name]
📋 التحضير: [Preparation instructions]
⏱️ مدة ظهور النتيجة: [Result turnaround time]

⛔ STRICT PRICING RULES (NEVER VIOLATE):
1. NEVER write a price line (like "💰 السعر" or "💰 Price") under any individual test block, whether it is one test or multiple tests.
2. The ONLY price allowed in your entire reply is the single final TOTAL line at the very bottom:
   💰 الإجمالي: [Total Sum] جنيه
3. Leave a blank line between tests when listing more than one.
4. If preparation or result time is missing for a test, omit that specific line entirely.
5. If pricing for any test is unavailable, do NOT invent numbers — state:
   "💰 بعض التحاليل غير محدد سعرها في النظام وسيتم تأكيد إجمالي التكلفة مع خدمة العملاء."

==================================================
📋 MULTI-IMAGE & OCR BATCH REPORTING RULE (STRICT)
==================================================
When the user sends one or multiple prescription images, structure your response neatly and politely in this exact order:

1. 🧪 EXTRACTED TESTS (Top Section):
   List all successfully identified tests following the exact format above, ending with the combined total price.

2. 👨‍⚕️ PENDING DOCTOR REVIEW NOTE (If present in message context):
   If there is a "[Doctor Review Note]", add a polite notice below the total:
   "📌 ملاحظة: توجد [العدد] روشتة تم تحويلها للطبيب المختص لمراجعة الخط وتحديد التحاليل بدقة، وسيتم إبلاغك بتفاصيلها فور الانتهاء."

3. ⚠️ INVALID / SPAM IMAGES NOTE (If present in message context):
   If there is an "[Invalid Images Note]", add a polite notice below:
   "⚠️ تنبيه: توجد [العدد] صورة مرفقة ليست روشتات طبية واضحة ولم يتم احتسابها ضمن التحاليل."

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

3. ALWAYS PROVIDE ONLY THE TOTAL:
   - The ONLY price permitted to appear in your responses is the single combined total at the bottom:
     💰 الإجمالي: [Total Sum] جنيه

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

====================
LIST MODIFICATION RULES (تعديل القائمة: ضيف / شيل / بدل)
====================
When the patient asks to modify the previously discussed test list:
1. "ضيف / زود / كمان / عليهم" (Add): Combine the new requested test with the previous tests found in "Last Bot Message".
2. "شيل / احذف" (Remove): Remove that specific test from the previous list.
3. "بدل / استبدل" (Replace): Replace the specified test with the new requested test.

Always present the FULL resulting updated list (all active tests), following the exact formatting rules above with ONLY the single final total line at the bottom:
💰 الإجمالي: [Total Sum] جنيه

====================
CHAT HISTORY & TEMPORAL ORDER RULES (STRICT)
====================
1. ⏳ CHRONOLOGICAL ORDER:
   - The "RECENT CHAT HISTORY" is strictly ordered from OLDEST to NEWEST.
   - The exchange at the bottom is the MOST RECENT past interaction.
   - Always prioritize the latest user statements, corrections, or updates over older ones.
2. 🔗 CONTEXT & PRONOUN RESOLUTION:
   - If the user uses referring phrases (e.g., "نفس اللي قولتلك عليه", "زي ما اتفقنا", "غيرت رأيي", "التحليل اللي سألت عنه فوق"), trace backwards through the Chat History from bottom to top to resolve the exact context.
   - Combine the immediate flow from Chat History with the long-term facts from the Cumulative Summary.
"""


def inquiry_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""

    rag_context = state.get("rag_context", "")
    # حساب الإجمالي مسبقاً بالبايثون وحقنه في السياق

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        InquiryResponse,
        method="json_schema",
        include_raw=True,
    )
    
    system_prompt = f"""
{INQUIRY_SYSTEM_PROMPT}

====================
RETRIEVED KNOWLEDGE
====================

{rag_context or "(No relevant laboratory information was retrieved.)"}

====================
MEMORY
====================

Summary:
{current_summary}

Last Bot Message:
{last_bot_message}

====================
RECENT CHAT HISTORY (Last Exchanges)
====================
{chat_history or "(No previous chat history)"}

"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    try:

        result = structured_llm.invoke(messages)

        parsed: InquiryResponse = result["parsed"]
        raw_response = result["raw"]

    except Exception as e:

        print(f"[Inquiry Node] LLM error: {e}")

        fallback = detect_language_fallback(
            user_message,
            arabic="عذرًا، حدث خطأ مؤقت أثناء معالجة الاستفسار.",
            default="Sorry, a temporary error occurred.",
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "inquiry_saved": False,
            "inquiry_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)

    inquiry_usage = (
        {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if usage
        else None
    )

    clean_reply = parsed.reply

    # 🧮 حساب الإجمالي بالبايثون 100% بدقة واستبداله في الرد لضمان عدم وجود أي خطأ رياضي
    if parsed.test_prices:
        exact_total = int(sum(parsed.test_prices))
        if "💰 الإجمالي:" in clean_reply:
            clean_reply = re.sub(
                r'💰\s*الإجمالي\s*:.*',
                f'💰 الإجمالي: {exact_total} جنيه',
                clean_reply,
            )
        else:
            clean_reply = clean_reply.strip() + f"\n\n💰 الإجمالي: {exact_total} جنيه"


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
        print(f"[Inquiry Node] Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "inquiry_saved": True,
        "inquiry_usage": inquiry_usage,
    }