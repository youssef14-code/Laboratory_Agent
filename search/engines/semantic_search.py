import logging

from knowledge.embedding import generate_embedding
import knowledge.vector_store as vs
from ..schemas import SearchResult

logger = logging.getLogger(__name__)


def semantic_search(
    query: str,
    description: str | None = None,
    limit: int = 5,
) -> list[SearchResult]:

    if not query.strip():
        return []

    search_text = query.strip()
    if description:
        search_text += "\n" + description.strip()

    try:
        query_embedding = generate_embedding(search_text)
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
    ]
