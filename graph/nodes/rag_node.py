import logging
from types import SimpleNamespace

from graph.state import AgentState
from rag.context_builder import build_context
from search.search_manager import run_search

logger = logging.getLogger(__name__)


def rag_node(state: AgentState) -> dict:
    sender_id = state.get("sender_id")
    refined_queries = state.get("refined_queries") or []

    # ⚡ 1. خطوة التسريع الفوري: لو مفيش استفسار عن تحاليل طبية، نتخطى البحث فوراً
    if not refined_queries:
        logger.info("[RAG Node] Skipped (No refined queries) | sender_id=%s", sender_id)
        return {
            "rag_context": state.get("rag_context", ""),
            "search_results": [],
            "top_score": 0.0,
        }

    # استخراج الاستفسارات الصالحة
    queries = [rq for rq in refined_queries if rq and getattr(rq, "query", None)]
    if not queries:
        return {
            "rag_context": state.get("rag_context", ""),
            "search_results": [],
            "top_score": 0.0,
        }

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

        print("\n" + "─" * 60)
        print(f"[RAG Node] ✅ تم البحث بنجاح!")
        print(f"[RAG Node] 📦 النتائج: {len(results)} تحليل مطابق")
        print(f"[RAG Node] 🎯 أعلى نسبة تطابق: {top_score:.4f}")
        print(f"[RAG Node] 📝 حجم الـ Context: {len(context)} حرف")

        if results:
            from models.models import LabService

            print(f"[RAG Node] 📋 تفاصيل كل النتائج ({len(results)}):")
            for i, r in enumerate(results, 1):
                r_id = getattr(r, "id", "?")
                r_name = getattr(r, "name", "?")
                r_score = getattr(r, "score", "?")
                r_source = getattr(r, "source", "?")

                print(f"     {i}. id={r_id:<5} score={r_score:<6} source={r_source:<15} name={r_name}")

                try:
                    lab = LabService.query.get(r_id)
                except Exception as e:
                    lab = None
                    print(f"        ⚠️ تعذر جلب تفاصيل id={r_id}: {e}")

                if lab:
                    if "fuzzy" in str(r_source):
                        print(f"        [fuzzy match on] aliases : {lab.alias_names}")
                    if "semantic" in str(r_source):
                        print(f"        [semantic match on] description : {str(lab.description)[:150]}...")
                        print(f"        [semantic match on] keywords    : {lab.keywords}")
        else:
            print("[RAG Node] ⚠️ مفيش أي نتايج راجعة خالص من run_search.")

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
        return {
            "rag_context": "",
            "search_results": [],
            "top_score": 0.0,
        }