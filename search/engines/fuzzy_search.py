from sqlalchemy import text
from rapidfuzz import fuzz

from knowledge.utils import main_session
from search.preprocess.normalize import normalize
from search.preprocess.ngram import ngram_similarity
from ..schemas import SearchResult

TABLE_NAME = "labservices"
MIN_SCORE = 0.45  # final score (0-1)


def _score_against(normalized_query: str, candidate: str) -> float:
    """بيحسب score واحد بين النص المطلوب وأي نص مرشح (اسم أو alias)."""
    normalized_candidate = normalize(candidate)

    if not normalized_candidate:
        return 0.0

    rapid = max(
        fuzz.partial_ratio(normalized_query, normalized_candidate),
        fuzz.token_set_ratio(normalized_query, normalized_candidate),
    ) / 100

    ngram = ngram_similarity(normalized_query, normalized_candidate)

    return (rapid + ngram) / 2


def fuzzy_search(
    query: str,
    limit: int = 2,
) -> list[SearchResult]:

    normalized_query = normalize(query)

    if not normalized_query:
        return []

    with main_session() as session:
        rows = session.execute(
            text(f"SELECT id, name, alias_names FROM {TABLE_NAME}")
        ).fetchall()

    scored = []

    for row in rows:
        # score على الاسم الأساسي
        best_score = _score_against(normalized_query, row.name)

        # alias_names متخزنة كنص مفصول بفاصلة (CSV) — بنقارن على كل alias لوحده
        if row.alias_names:
            for alias in row.alias_names.split(","):
                alias = alias.strip()
                if not alias:
                    continue
                alias_score = _score_against(normalized_query, alias)
                if alias_score > best_score:
                    best_score = alias_score

        if best_score >= MIN_SCORE:
            scored.append((row, best_score))

    scored.sort(key=lambda x: x[1], reverse=True)

    results = [
        SearchResult(
            id=row.id,
            name=row.name,
            score=round(final_score, 3),
            source="fuzzy",
        )
        for row, final_score in scored[:limit]
    ]

    return results