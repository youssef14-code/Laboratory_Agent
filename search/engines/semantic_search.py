import logging

from knowledge.embedding import generate_embedding, build_search_text
import knowledge.vector_store as vs
from ..schemas import SearchResult

logger = logging.getLogger(__name__)

MIN_SCORE = 0.6  # final cosine-similarity score (0-1) — ظبطها لو لاحظت
                 # نتائج قوية بتتشال أو ضعيفة بتفضل، بناءً على تجارب حقيقية


def semantic_search(
    query: str,
    keywords: list[str] | None = None,
    description: str | None = None,
    limit: int = 3,
) -> list[SearchResult]:

    if not query.strip():
        return []

    # نبني نص الـ query بنفس التمبلت اللي اتعمل بيه embedding للـ documents
    # (description + keywords) عشان الـ query يقع في نفس الفضاء الدلالي.
    # query نفسها + الـ keywords الجاية من الـ RefinedQuery بيتحطوا مع
    # بعض كـ "keywords"، والـ description بتتحط منفصلة زي الـ documents.
    combined_keywords = [query.strip()] + [
        k.strip() for k in (keywords or []) if k and k.strip()
    ]

    search_text = build_search_text(
        name="",
        description=description or "",
        keywords=combined_keywords,
    )

    if not search_text:
        return []


    try:
        # task_type="retrieval_query" مهم هنا — الـ documents المخزنة في
        # الـ FAISS اتعملها embedding بـ "retrieval_document"، فلازم الـ
        # query يتعمله embedding بـ task_type مختلف ("retrieval_query")
        # عشان الموديل (asymmetric) يدي مطابقة أدق بين السؤال والمستندات.
        query_embedding = generate_embedding(search_text, task_type="retrieval_query")
    except Exception as exc:
        logger.warning("[Semantic Search] Embedding generation failed: %s", exc)
        return []

    try:
        raw_results = vs.search(query_embedding, k=limit)
    except Exception as exc:
        logger.warning("[Semantic Search] FAISS search failed: %s", exc)
        return []

    return [
        SearchResult(
            id=r["id"],
            name=r["name"],
            score=round(r["score"], 3),
            source="semantic",
        )
        for r in raw_results
        if r["score"] >= MIN_SCORE
    ]
