import logging
from langchain_core.messages import HumanMessage, SystemMessage

from graph.schemas.intent_sechema import IntentResponse, IntentType
from graph.state import AgentState
from llm.llm import get_gemini

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """
You are responsible ONLY for routing and search query generation.

You NEVER answer the user.
You ONLY return the structured output.

====================================================
SOURCE OF TRUTH FOR TEST NAMES
====================================================

1. Current Message (Highest Priority):
   If the current message explicitly names a lab test, generate the query directly from it.

2. Short Follow-ups:
   If the message is a short follow-up without naming a test (e.g. "بكام", "مدة النتيجة", "الصيام كام ساعة"), use the tests in "Last Bot Message" ONLY. Do not dig into older turns.

3. Explicit Past References (Exception):
   ONLY trace backwards into "RECENT CHAT HISTORY" if the user explicitly uses referring phrases pointing to past turns (e.g. "التحليل اللي سألت عنه فوق", "نفس اللي قولتلك عليه في الأول", "غيرت رأيي وهرجع للتحليل الأول").

4. Negative Rule:
   If no test is named, no explicit past reference exists, and "Last Bot Message" contains no tests, return refined_queries = [].
   
====================================================
TASK 1 : Intent Classification
====================================================

Choose exactly ONE intent:

visit
The user wants to book, continue a booking, confirm a booking, provides a prescription (روشتة) for booking a home visit.

inquiry
The user asks about laboratory tests, prices, availability, preparation instructions, result duration, mentions medical symptoms, or asks general medical laboratory questions.

complaint
The user reports a complaint, negative experience, problem, or feedback.

direct
Greetings, thanks, small talk, working hours, lab location/branches, contact numbers, or anything unrelated to laboratory test retrieval.

labresults
The user asks how to get/download lab results, asks if results are ready, or inquires about anything directly connected to retrieving lab results.

====================================================
TASK 2 : Refined Search Queries (CRITICAL FOR RAG)
====================================================

Generate one RefinedQuery for each identifiable laboratory test, medical test, panel, medical abbreviation, or symptom-based test.

🎯 SCOPE & SPECIFICITY RULES:
1. 🧪 Preserve Exact Scope:
   - Match what kind of entity was asked for: a single specific test must NOT be widened into a panel/package (e.g. asking for "ALT" should NOT be expanded to "Liver Function Panel"), and a panel must NOT be narrowed into one component test.
2. 📄 OCR Prescriptions:
   - If the message starts with "[Prescription OCR Extracted Text]":
   - Read the transcribed prescription text with extreme medical precision.
   - Extract ALL laboratory tests, blood tests, urine/stool tests, hormone assays, and cultures.
   - Ignore medications, oral dosages, or doctor clinic info that are not laboratory tests.
3. 🌐 Canonical English Names:
   - `query` MUST be the formal canonical medical English name or descriptive phrase combining test name and what it measures.
4. 🇸🇦 Rich Arabic & English Aliases (For Exact & Fuzzy Matching):
   - `aliases` MUST include:
     * Popular abbreviations (e.g., "CBC", "FBS", "TSH", "ALT", "SGPT").
     * Exact Egyptian/Arabic medical terms (e.g., "صورة دم", "صورة دم كاملة", "سكر صائم", "تحليل الغدة الدرقية", "انزيمات الكبد").
     * Common phonetic transliterations and slang.
5. 🧬 Medical Keywords & Description (For Semantic Vector Search):
   - `keywords`: 3-7 distinctive retrieval keywords directly related to the test (prefer terms describing analyte, specimen, method; avoid generic terms like "blood test").
   - `description`: A clear, precise medical description explaining what the test measures.
6. 🚫 Strict Negative Rule:
   - If the message is purely conversational (e.g., "سلام عليكم", "تمام", "عايز احجز يوم الجمعة") and mentions NO test names or medical symptoms, return `refined_queries = []`.

====================================================
TASK 3.5 : "كفاءة" vs "وظائف" — SPECIFICITY RULE
====================================================

These two Arabic words are NOT interchangeable when attached to any organ or system name:

"كفاءة" (efficiency / rate / clearance) + [organ/system] →
  Refers to a SINGLE, SPECIFIC test measuring that organ's functional rate or clearance (e.g. "كفاءة كلى" maps to eGFR / Creatinine Clearance). It does NOT refer to a bundled panel.

"وظائف" (function panel) + [organ/system] →
  Refers to the organ's FUNCTION TEST PANEL — a set of multiple related analytes bundled together (e.g. "وظائف كبد" -> Liver Function Tests, "وظائف كلى" -> Kidney Function Tests).

Never substitute a broader bundled panel for a request that used "كفاءة".

====================================================
TASK 4 : Conversation Continuation
====================================================

Inspect "Last Bot Message" and "RECENT CHAT HISTORY" to determine what the current message is responding to:

ACTIVE BOOKING FLOW:
If Last Bot Message requested booking information (name, phone, address, date) and the current message provides or confirms it:
→ intent = visit.

ACTIVE INQUIRY FLOW:
If Last Bot Message provided laboratory information and the current message asks a follow-up or adds a test:
→ intent = inquiry.

ACTIVE COMPLAINT FLOW:
If Last Bot Message requested complaint details and the current message provides it:
→ intent = complaint.

If Last Bot Message and conversation context disagree, Last Bot Message wins.

====================================================
TASK 5 : Pending Prescription / Doctor Review
====================================================

If the "Summary" indicates that the user is waiting for a doctor to review an uploaded prescription (e.g., "waiting for manual doctor review"), and the user asks a short follow-up like "كام", "بكام", "خلصت ولا لسه":

→ intent = direct
→ refined_queries = []

CRITICAL: Do NOT classify this as 'inquiry'. Do NOT extract or use past tests from RECENT CHAT HISTORY. Force intent to 'direct' with empty queries.

====================================================
FEW-SHOT EXAMPLES:
====================================================

Example 1: User says "عايز اعمل صورة دم وسكر صائم وكفاءة كلى"
Output Refined Queries:
1. query: "Complete Blood Count"
   aliases: ["CBC", "صورة دم", "صورة دم كاملة", "هيموجلوبين", "كريات الدم"]
   keywords: ["blood", "anemia", "platelets", "hemoglobin", "hematology", "leukocytes"]
   description: "Quantifies red blood cells, white blood cells, platelets, and hemoglobin to detect anemia and infections."
2. query: "Fasting Blood Glucose"
   aliases: ["FBS", "Fasting Blood Sugar", "سكر صائم", "تحليل السكر الصائم", "جلوكوز صائم"]
   keywords: ["glucose", "sugar", "diabetes", "fasting", "metabolism", "endocrine"]
   description: "Measures blood glucose levels after an overnight fast to diagnose and monitor diabetes."
3. query: "eGFR / Kidney Efficiency"
   aliases: ["eGFR", "كفاءة كلى", "معدل الترشيح الكبيبي", "Creatinine Clearance", "كفاءة الكلية"]
   keywords: ["filtration rate", "renal efficiency", "glomerular", "clearance", "kidney rate"]
   description: "Measures kidney filtration efficiency and glomerular filtration rate."

Example 2: User says "عايز وظائف كبد"
Output Refined Queries:
1. query: "Liver Function Tests"
   aliases: ["LFT", "انزيمات الكبد", "وظائف كبد", "ALT", "AST", "SGPT", "SGOT", "تحاليل الكبد"]
   keywords: ["liver", "hepatic", "enzymes", "transaminases", "bilirubin", "hepatitis"]
   description: "Evaluates liver health and enzyme levels including ALT, AST, Bilirubin, and Albumin."


   
====================
.CHAT HISTORY & TEMPORAL ORDER RULES (STRICT)
====================
1. ⏳ CHRONOLOGICAL ORDER:
   - The "RECENT CHAT HISTORY" is strictly ordered from OLDEST to NEWEST.
   - The exchange at the bottom is the MOST RECENT past interaction.
   - Always prioritize the latest user statements, corrections, or updates over older ones.
2. 🔗 CONTEXT & PRONOUN RESOLUTION:
   - If the user uses referring phrases (e.g., "نفس اللي قولتلك عليه", "زي ما اتفقنا", "غيرت رأيي", "التحليل اللي سألت عنه فوق"), trace backwards through the Chat History from bottom to top to resolve the exact context.
   - Combine the immediate flow from Chat History with the long-term facts from the Cumulative Summary.

"""


def intent_node(state: AgentState) -> dict:

    sender_id = state.get("sender_id")
    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    chat_history = state.get("chat_history") or ""

    logger.info(
        "[Intent Node] start | sender_id=%s | message=%r",
        sender_id,
        user_message[:100],
    )

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        IntentResponse,
        method="json_schema",
        include_raw=True,
    )

    system_prompt = f"""
{INTENT_SYSTEM_PROMPT}

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

        parsed: IntentResponse = result["parsed"]
        raw_response = result["raw"]
        print(f"[Intent Node] LLM raw response: {parsed.intent.value} ")

    except Exception as e:
        print(f"[Intent Node] LLM raw response: {parsed.intent.value}")

        logger.error(
            "[Intent Node] LLM error | sender_id=%s | error=%s",
            sender_id,
            e,
        )

        return {
            "intent": IntentType.DIRECT.value,
            "refined_queries": [],
            "intent_usage": None,
        }

    usage = getattr(raw_response, "usage_metadata", None)

    intent_usage = (
        {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if usage
        else None
    )

    queries_extracted = [q.query for q in (parsed.refined_queries or [])]

    logger.info(
        "[Intent Node] classified | sender_id=%s | intent=%s | refined_queries=%r",
        sender_id,
        parsed.intent.value,
        queries_extracted,
    )
    # طباعة تفصيلية لكل refined query استُخرجت
    refined = parsed.refined_queries or []
    print("\n" + "─" * 60)
    print(f"[Intent Node] ✅ Intent    : {parsed.intent.value}")
    print(f"[Intent Node] 🔍 Refined Queries ({len(refined)} extracted):")
    for i, q in enumerate(refined, 1):
        print(f"   {i}. query       : {q.query}")
        print(f"      aliases     : {q.aliases}")
        print(f"      keywords    : {q.keywords}")
        print(f"      description : {q.description}")
    print("─" * 60 + "\n")


    return {
        "intent": parsed.intent.value,
        "refined_queries": parsed.refined_queries,
        "intent_usage": intent_usage,
    }
    