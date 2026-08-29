import logging
from types import SimpleNamespace

from graph.state import AgentState
from rag.context_builder import build_context
from search.search_manager import run_search

logger = logging.getLogger(__name__)


def rag_node(state: AgentState) -> dict:

    sender_id = state.get("sender_id")
    user_message = state.get("user_message", "")
    refined_queries = state.get("refined_queries") or []

    # استخدام الـ Refined Queries إن وجدت، أو الاعتماد على رسالة المستخدم كـ Fallback
    if refined_queries:
        queries = [rq for rq in refined_queries if rq and getattr(rq, "query", None)]
    else:
        queries = [SimpleNamespace(query=user_message, aliases=[], keywords=[], description="")]

    query_names = [getattr(q, "query", str(q)) for q in queries]

    logger.info(
        "[RAG Node] start | sender_id=%s | queries=%r",
        sender_id,
        query_names,
    )

    try:

        search = run_search(queries)

        results = search.get("results", [])
        top_score = search.get("top_score", 0.0)
        context = build_context(results)
                 # بعد نجاح البحث
        print("\n" + "─" * 60)
        print(f"[RAG Node] ✅ تم البحث بنجاح!")
        print(f"[RAG Node] 📦 النتائج: {len(results)} تحليل مطابق")
        print(f"[RAG Node] 🎯 أعلى نسبة تطابق: {top_score:.4f}")
        print(f"[RAG Node] 📝 حجم الـ Context: {len(context)} حرف")
        print("─" * 60 + "\n")

        logger.info(
            "[RAG Node] done | sender_id=%s | results_count=%d | top_score=%s",
            sender_id,
            len(results),
            top_score,
        )

        return {
            "rag_context": context,
            "search_results": results,
            "top_score": top_score,
        }

    except Exception as e:

        logger.error(
            "[RAG Node] Search error | sender_id=%s | error=%s",
            sender_id,
            e,
        )

        # إرجاع سياق فارغ آمن في حالة حدوث خطأ لضمان استمرار عمل النودات التالية
        return {
            "rag_context": "",
            "search_results": [],
            "top_score": 0.0,
        }