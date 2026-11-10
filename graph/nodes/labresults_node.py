import logging
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from graph.state import AgentState
from graph.utils import detect_language_fallback
from llm.llm import get_gemini
from models.models import Page
from software_service.client_services import ClientService
from software_service.result_request_services import ResultRequestService

logger = logging.getLogger(__name__)


class LabResultsResponse(BaseModel):
    reply: str = Field(
        description=(
            "Polite response in Egyptian Arabic informing the user that their request/inquiry "
            "regarding the lab results has been received and customer service will contact them."
        )
    )
    summary: str = Field(
        description=(
            "Updated English conversation summary. "
            "Always preserve all previously collected information "
            "(customer name, phone, booking details, complaints, test inquiries, and result requests)."
        )
    )


LABRESULTS_SYSTEM_PROMPT = """
You are a polite, helpful laboratory customer service assistant.

Your task is to handle patient inquiries about laboratory test results, such as:
- "ازاي أجيب النتيجة؟"
- "نتيجتي ظهرت ولا لسه؟"
- "عايز رابط النتيجة"
- "التحاليل خلصت؟"
- "النتيجة هتطلع إمتى؟"
- "إيه أخبار النتيجة بتاعتي؟"
- "النتيجة اتأخرت ليه؟"

==================================================
🎯 CORE MANDATORY MESSAGE
==================================================
Whenever a patient inquires about their results (status, timing, updates, delivery, or delays):
Your primary and mandatory message MUST state clearly that their inquiry request has been received and customer service will contact them:
"استلمنا طلبك للاستفسار عن النتيجة وخدمة العملاء هتتواصل معاك"

You must use natural, warm Egyptian Arabic phrasing with polite variations, for example:
- "أهلاً بك يا فندم، استلمنا طلبك للاستفسار عن النتيجة وفريق خدمة العملاء هيتواصل مع حضرتك في أقرب وقت."
- "تمام يا فندم، تم تسجيل طلب استفسارك بخصوص النتيجة، وخدمة العملاء هتتواصل معاك لمتابعتها."

====================
RULES
====================

1. INTENT UNDERSTANDING
Recognize ALL inquiries related to laboratory results, including:
- Inquiring whether results are ready or when they will be ready.
- Asking for a result link, PDF, WhatsApp, or SMS delivery.
- Following up on pending or delayed results.
- Inquiring about receiving results online.
- Patients providing details (patient name, phone, invoice, or test name).
- Complaints regarding waiting times for results.

2. REQUEST HANDLING & STATUS
- Treat every result inquiry as an acknowledged follow-up request.
- The registration has already been logged by the system; your role is to reassure the patient immediately.
- Do NOT interrogate the patient or demand extra fields if not provided.
- Do NOT instruct the patient to call the branch, visit the lab, or seek results elsewhere.
- If the patient is asking a repeat question or complaining about delay (e.g. "محدش كلمني ليه"):
  Politely acknowledge and apologize for the wait, and confirm their request is prioritized with customer service (e.g., "بنعتذر لحضرتك عن الانتظار، طلبك متسجل ومُرسل لخدمة العملاء وهيتم التواصل مع حضرتك في أسرع وقت").

3. CONTEXTUAL & EMPATHETIC RESPONSE
- Keep the response short, conversational, and direct.
- Acknowledge urgency or frustration empathetically before giving the reassurance.
- If the patient asks multiple things (e.g., asked about the result and asked about branch timings), answer the other question politely while keeping the core reassurance regarding the result inquiry.

4. STRICT LIMITATIONS
- NEVER guess, invent, or state whether the test result is positive/negative, normal/abnormal, or ready/not ready.
- NEVER invent turnaround times (e.g., do not say "هتطلع بعد ساعتين" or "بكرة الصبح").
- NEVER claim that you personally checked the lab database or saw the report.
- NEVER invent reference numbers, tracking IDs, or promises of specific delivery channels.

5. CONVERSATION MEMORY (SUMMARY)
- Update the conversation summary in clear English.
- Retain all historical details: customer name, phone number, branch, test names, and booking history.
- Explicitly record: "Result inquiry logged for customer service follow-up."
- If the customer provided test names or reference details in the current message, capture them in the summary.

==================================================
🌐 MANDATORY LANGUAGE RULE (STRICT EGYPTIAN ARABIC)
==================================================
1. USER-FACING LANGUAGE IS ARABIC (STRICT):
   - You MUST ALWAYS speak and reply to the patient in friendly, polite Egyptian Arabic.
   - Even though the system prompt, instructions, and internal summary are in English, YOUR FINAL 'reply' MUST BE IN ARABIC.
2. ENGLISH EXCEPTION ONLY:
   - Reply in English ONLY if the user's message is entirely written in English, or if they explicitly ask to speak in English.

==================================================
⏳ CHAT HISTORY & CONTEXT RESOLUTION
==================================================
1. CHRONOLOGICAL ORDER:
   - "RECENT CHAT HISTORY" is sorted from OLDEST to NEWEST. The bottom message is the most recent.
2. PRONOUN & CONTEXT RESOLUTION:
   - Resolve references like ("بخصوص التحليل اللي سألت عليه", "زي ما قولتلك") using the history and memory.
"""


def result_node(state: AgentState) -> dict:
    identity = str(state.get("sender_identity") or state.get("sender_id") or "").strip()
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")
    try:
        page = Page.query.filter_by(
            platform_id=platform_id,
            page_id=page_id,
        ).first()
        laboratory_id = page.laboratory_id if page else None
        ResultRequestService.create_request(identity, laboratory_id)
    except Exception:
        logger.exception("[LabResults Node] Result request persist error")
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
        # Fallback updated to match the desired reply directly
        fallback = detect_language_fallback(
            user_message,
            arabic="أهلاً بك! تم استلام طلبك للاستفسار عن النتيجة وخدمة العملاء هتتواصل معاك في أقرب وقت.",
            default="Hello! We have received your inquiry regarding your lab results, and customer service will contact you shortly.",
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