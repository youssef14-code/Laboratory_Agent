from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.complaint_tool import save_complaint_tool
from graph.schemas.complaint_sechema import ComplaintResponse
from graph.state import AgentState
from graph.utils import detect_language_fallback
from llm.llm import get_gemini
from software_service.client_services import ClientService

COMPLAINT_SYSTEM_PROMPT = """
You are a professional customer support assistant for a medical laboratory.

Your task is to register customer complaints politely and efficiently.

====================
REQUIRED FIELDS
====================

- phone: User's contact phone number.
- complaint_text: Clear description of the user's issue/complaint.

====================
RULES
====================

1. Never ask for fields that are already provided in the conversation summary or memory.
2. Ask for only ONE missing field at a time in a friendly and concise manner.
3. Match the user's language.
4. Set confirmed=true ONLY when the user explicitly confirms submitting the complaint (e.g., تمام، سجل، اه، أيوة، yes, submit).
5. Set ready_to_save=true ONLY if phone and complaint_text are both available.
6. Update the conversation summary while preserving all previously collected information, including customer information, booking information, complaint details, and relevant history. Never remove unrelated information from the summary.

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


def complaint_node(state: AgentState) -> dict:

    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        ComplaintResponse,
        method="json_schema",
        include_raw=True,
    )

    system_prompt = f"""
{COMPLAINT_SYSTEM_PROMPT}

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

        parsed: ComplaintResponse = result["parsed"]
        raw_response = result["raw"]

    except Exception as e:

        print(f"[Complaint Node] LLM error: {e}")

        fallback = detect_language_fallback(
            user_message,
            arabic="عذرًا، حدث خطأ مؤقت أثناء تسجيل الشكوى.",
            default="Sorry, a temporary error occurred while processing your complaint.",
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "complaint_saved": False,
            "complaint_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)

    complaint_usage = (
        {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if usage
        else None
    )

    complaint_data = parsed.complaint.model_dump(exclude_none=True)
    required_fields = ["phone", "complaint_text"]
    all_fields_present = all(complaint_data.get(field) for field in required_fields)

    complaint_saved = False
    clean_reply = parsed.reply

    # استدعاء التول عند اكتمال البيانات والتأكيد
    if parsed.ready_to_save and parsed.confirmed and all_fields_present:

        try:

            result = save_complaint_tool.invoke(
                input={
                    **complaint_data,
                    "comes_from": str(platform_id or "unknown"),
                }
            )

            if result.success:

                complaint_saved = True

                clean_reply = detect_language_fallback(
                    user_message,
                    arabic="تم تسجيل شكواك بنجاح ✅ وسيتواصل معك فريقنا في أقرب وقت.",
                    default="Your complaint has been successfully registered. Our team will contact you soon.",
                )

            else:
                raise ValueError(result.message)

        except Exception as e:

            print(f"[Complaint Node] Tool error: {e}")

            complaint_saved = False
            parsed.summary = current_summary

            clean_reply = detect_language_fallback(
                user_message,
                arabic="حدث خطأ أثناء تسجيل الشكوى. حاول مرة أخرى.",
                default="An error occurred while saving your complaint. Please try again.",
            )

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
        print(f"[Complaint Node] Persist error: {e}")

    return {
        "response": clean_reply,
        "summary": parsed.summary,
        "last_bot_message": clean_reply,
        "complaint_saved": complaint_saved,
        "complaint_usage": complaint_usage,
    }