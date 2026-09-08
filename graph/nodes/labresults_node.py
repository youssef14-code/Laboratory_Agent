import logging
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from graph.state import AgentState
from graph.utils import detect_language_fallback
from llm.llm import get_gemini
from software_service.client_services import ClientService

logger = logging.getLogger(__name__)


class LabResultsResponse(BaseModel):
    reply: str = Field(
        description="Polite response informing the user that their results link will be sent to them via message."
    )
    summary: str = Field(
        description=(
            "Updated English conversation summary. "
            "Always preserve all previously collected information "
            "(customer name, phone, booking details, complaints, test inquiries, and result requests)."
        )
    )


LABRESULTS_SYSTEM_PROMPT = """
You are a helpful laboratory customer service assistant.

Your task is to handle patient inquiries about laboratory test results,
such as:

- "ازاي أجيب النتيجة؟"
- "نتيجتي ظهرت ولا لسه؟"
- "عايز رابط النتيجة"
- "التحاليل خلصت؟"

====================
RULES
====================

1. If the patient asks about laboratory results, result status, result
   availability, or how to receive the results, politely instruct them to
   contact the laboratory branch where the tests were performed.

2. Do NOT claim that results will be sent automatically by message,
   WhatsApp, SMS, or a secure link.

3. Do NOT claim that the results are ready or not ready because you cannot
   access or verify the patient's laboratory results.

4. If the patient provides a phone number, reference number, patient name,
   or test name, acknowledge it politely, but do not claim that you verified
   the result.

5. Match the patient's language. Default to polite Egyptian Arabic.

6. Never invent test results, medical values, diagnoses, result links,
   reference numbers, or result availability.

7. Keep the response short and direct.

Suggested Egyptian Arabic response:

"لمتابعة نتيجة التحاليل والتأكد إذا كانت ظهرت، من فضلك تواصل مباشرةً مع الفرع اللي عملت فيه التحاليل، لأن متابعة النتائج متاحة حاليًا من خلال الفرع."

8. Update the conversation summary while preserving all previous relevant
   information. Record that the patient asked about laboratory results and
   was directed to contact the relevant branch.
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


def result_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        LabResultsResponse,
        include_raw=True,
    )

    system_prompt = f"""
{LABRESULTS_SYSTEM_PROMPT}

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

        parsed: LabResultsResponse = result["parsed"]
        raw_response = result["raw"]

    except Exception as e:

        logger.error(f"[LabResults Node] LLM error: {e}")

        fallback = detect_language_fallback(
            user_message,
            arabic="أهلاً بك! سيتم إرسال رابط نتيجة التحليل لك في رسالة فور اعتمادها من المعمل.",
            default="Hello! Your lab results link will be sent to you via message as soon as it is approved by the lab.",
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "labresults_saved": False,
            "labresults_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)

    labresults_usage = (
        {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if usage
        else None
    )

    clean_reply = parsed.reply

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
        logger.error(f"[LabResults Node] Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "labresults_saved": True,
        "labresults_usage": labresults_usage,
    }