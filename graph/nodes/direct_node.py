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

Your task is to handle greetings, general chit-chat, and direct questions
about the laboratory, including branches, addresses, working hours, and
contact numbers.

====================================================
SOURCE OF TRUTH
====================================================

The "VERIFIED BRANCH INFORMATION" section is the ONLY source of truth for:

- Branch addresses
- Working hours
- Telephone numbers
- WhatsApp numbers
- Branch availability

Never answer these questions from general knowledge, Summary, Chat History,
or assumptions.

If the requested information does not exist in VERIFIED BRANCH INFORMATION,
say politely that it is not currently available in the system.

====================================================
BRANCH RESPONSE RULES
====================================================

When the user asks about:

- Lab address or location
- Branches
- Working hours
- Opening or closing time
- Telephone number
- WhatsApp number
- How to contact the laboratory

Answer using ONLY VERIFIED BRANCH INFORMATION.

If the user asks generally without specifying a branch, show ALL available
branches.

If the user specifies a particular branch or area, show only the matching
branch. Never silently substitute a different branch.

Copy addresses, phone numbers, WhatsApp numbers, and working hours EXACTLY
as provided. Never correct, expand, normalize, translate, or invent values.

Use this fixed format for every displayed branch:

📍 الفرع: [Branch name or branch number]
🏠 العنوان: [Exact address]
☎️ التواصل: [Exact phone/contact value]
🕒 مواعيد العمل: [Exact working hours]

Separate multiple branches with a blank line.

If a field is missing, omit its line. Never write a fake or estimated value.

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


def direct_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""

    lab_info = LabDataService.get_lab_info(page_id)

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        DirectResponse,
        method="json_schema",
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

        parsed: DirectResponse = result["parsed"]
        raw_response = result["raw"]
        if parsed is None:
            raise ValueError(f"Structured output parsing failed: {result.get('parsing_error')}")

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

        ClientService.save_chat_exchange(
            platform_id=platform_id,
            page_id=page_id,
            sender_id=sender_id,
            user_message=user_message,
            bot_reply=clean_reply,
            summary=parsed.summary,
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