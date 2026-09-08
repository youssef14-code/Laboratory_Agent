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