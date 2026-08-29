from langchain_core.messages import HumanMessage, SystemMessage

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
LAB INFORMATION FORMATTING
====================

don't give the user any test or lab without this FORMATIING

When presenting laboratory tests from the Retrieved Knowledge, there are
TWO cases depending on how many tests are being presented:

--------------------
CASE A — Single test
--------------------
The user is asking about exactly ONE specific test. Use this exact
structure:

🧪 Test Name
💰 Price: ...
📋 Preparation: ...
⏱️ Result: ...

--------------------
CASE B — Multiple tests (e.g. a prescription/روشتة, or the user names
several tests, or a general checkup lookup returns several tests)
--------------------
Do NOT show a price line next to each individual test. List each test
using ONLY:

🧪 Test Name
📋 Preparation: ...
⏱️ Result: ...

Then, after ALL the tests are listed, add ONE final line with the combined
total price of every test found in the Retrieved Knowledge, e.g.:

💰 الإجمالي: ... جنيه

Rules for both cases:

- Leave a blank line between tests when listing more than one.
- Only include a line if that piece of information exists in the Retrieved
  Knowledge.
- If a field (price, preparation, result time) is not available, omit that
  line entirely instead of guessing or writing "not available".
- If, in CASE B, the price is missing for one or more of the listed tests,
  do not compute a partial/misleading total — instead state that the full
  total isn't available because pricing for some tests is missing.
- Never invent or estimate any value that is missing.
- Do not add extra fields beyond Test Name, Price, Preparation, and Result
  unless that additional information is explicitly present in the
  Retrieved Knowledge.
- Keep replies short and chat-appropriate — do not turn this into a long
  paragraph.
- Do not repeat the same test information twice in one response.

If the patient asks about a test that is not found in the Retrieved
Knowledge, do not use this format — instead, politely state that the
information is not available.
"""


def inquiry_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    rag_context = state.get("rag_context", "")

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        InquiryResponse,
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

    try:

        ClientService.update_client_summary_and_last_bot_message(
            sender_id=sender_id,
            page_id=page_id,
            platform_id=platform_id,
            summary=parsed.summary,
            last_bot_message=clean_reply,
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