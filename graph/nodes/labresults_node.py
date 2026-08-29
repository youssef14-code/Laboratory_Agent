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

Your task is to handle patient inquiries about laboratory test results (e.g. "ازاي اجيب النتيجة؟", "نتيجتي ظهرت ولا لسه؟", "عايز رابط النتيجة").

====================
RULES
====================

1. Inform the user politely that their lab results will be sent to them directly in a message with a secure link (أو رسالة نصية/واتساب تحتوي على رابط النتيجة فور جاهزيتها).
2. Match the user's language (default to polite Arabic).
3. If the user provided a phone number or reference number, acknowledge it; otherwise, assure them that once the analysis is completed by the laboratory, the results link is sent automatically.
4. Never invent or provide fake medical test values or medical diagnoses.
5. Update the conversation summary while preserving all previously collected information (customer info, bookings, complaints, inquiries).
"""


def result_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

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
        ClientService.update_client_summary_and_last_bot_message(
            sender_id=sender_id,
            page_id=page_id,
            platform_id=platform_id,
            summary=parsed.summary,
            last_bot_message=clean_reply,
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