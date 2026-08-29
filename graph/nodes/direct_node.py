from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from graph.prompt_service.lab_data import LabDataService
from graph.state import AgentState
from graph.utils import detect_language_fallback
from llm.llm import get_gemini
from software_service.client_services import ClientService


class DirectResponse(BaseModel):
    reply: str = Field(
        description="The response message to the user."
    )
    summary: str = Field(
        description=(
            "Updated English conversation summary. "
            "Always preserve all previously collected information "
            "(customer name, phone, booking information, complaint information, "
            "and relevant history) so future turns can continue without losing context."
        )
    )


DIRECT_SYSTEM_PROMPT = """
You are a friendly laboratory customer service representative.

Your task is to handle greetings, general chit-chat, or direct inquiries about the laboratory (such as working hours, contact numbers, address, and branches).

====================
RULES
====================

1. Be polite, concise, and helpful.
2. Rely ONLY on the Laboratory Information provided. Do not make up or invent information.
3. Match the user's language.
4. Keep the conversation contextually natural and friendly.
5. NEVER instruct the patient to book a home visit or any service by phone call. This lab ONLY books home visits through this chat conversation itself (via the booking flow). If the user's message is ambiguous or unclear, politely ask them to clarify what they need (e.g., "تقصد إيه بالظبط؟ حابب تحجز زيارة منزلية ولا عندك سؤال عن تحليل معين؟") instead of guessing or offering a phone-call alternative.
6. Do not offer a phone number as a way to complete a booking. A phone number may only be shared if the user explicitly asks for the lab's contact number itself.
7. Update the conversation summary while preserving all previously collected information, including customer information, booking information, complaint details, and relevant inquiry history. Never remove unrelated information from the summary.
"""


def direct_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    lab_info = LabDataService.get_lab_info(page_id)

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        DirectResponse,
        include_raw=True,
    )

    system_prompt = f"""
{DIRECT_SYSTEM_PROMPT}

====================
LABORATORY INFORMATION
====================

{lab_info or "(No laboratory information available.)"}

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

        parsed: DirectResponse = result["parsed"]
        raw_response = result["raw"]

    except Exception as e:

        print(f"[Direct Node] LLM error: {e}")

        fallback = detect_language_fallback(
            user_message,
            arabic="أهلاً بك في مختبرنا الطبي! كيف يمكنني مساعدتك اليوم؟ يمكنك الاستفسار عن التحاليل، أو حجز زيارة منزلية، أو تسجيل شكوى.",
            default="Welcome to our medical laboratory! How can I help you today? You can inquire about tests, book a home visit, or submit a complaint.",
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "direct_saved": False,
            "direct_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)

    direct_usage = (
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
        print(f"[Direct Node] Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "direct_saved": True,
        "direct_usage": direct_usage,
    }