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
TASK 1 : Intent Classification
====================================================

Choose exactly ONE intent:

visit
The user wants to book, continue a booking, confirm a booking, or provides a prescription (روشتة) for booking a home visit.

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

Extract ONE search object for EVERY laboratory test, medical abbreviation, or prescription item mentioned by the user or extracted from OCR.

If the message starts with "[Prescription OCR Extracted Text]":
- Read through the transcribed prescription text carefully.
- Extract EVERY valid laboratory test or abbreviation (e.g. CBC, FBS, RBS, TSH, Lipid Profile, PT, Urine Analysis, Lupus Anticoagulant).
- Generate a refined search object for each extracted test so the RAG system can retrieve their prices and preparation instructions.

Each search object MUST contain:
• query: The canonical laboratory name (in English).
• aliases: Equivalent names/abbreviations (e.g. ["CBC", "صورة دم", "صورة دم كاملة"]).
• keywords: Medical keywords (e.g. ["blood", "anemia", "platelets"]).
• description: Short description for semantic search.

====================================================
TASK 3 : General Checkup / Reassurance Requests
====================================================

If the message is a general reassurance request without specific tests named:
1. Classify intent = "inquiry".
2. Leave refined_queries EMPTY for general checkups.

====================================================
RULES
====================================================

- Create one search object per laboratory entity explicitly named in the text or prescription.
- Do not invent laboratory tests that were not requested.
- Never answer the user directly.
"""


def intent_node(state: AgentState) -> dict:

    sender_id = state.get("sender_id")
    user_message = state["user_message"]

    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    logger.info(
        "[Intent Node] start | sender_id=%s | message=%r",
        sender_id,
        user_message[:100],
    )

    llm = get_gemini()
    structured_llm = llm.with_structured_output(
        IntentResponse,
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
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    try:

        result = structured_llm.invoke(messages)

        parsed: IntentResponse = result["parsed"]
        raw_response = result["raw"]

    except Exception as e:

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