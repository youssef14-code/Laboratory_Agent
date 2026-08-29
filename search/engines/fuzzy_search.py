import json
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


def _extract_alias_candidates(alias_names_raw: str) -> list[str]:
    """
    alias_names متخزنة كـ JSON object (شكل AliasNames في schemas.py):
    {"alias": "...", "measurement": "...", "equivalent_name": "...", "aliases": [...]}
    بنرجع كل القيم النصية اللي تستاهل تتقارن كـ alias مرشح.
    """
    if not alias_names_raw:
        return []

    try:
        parsed = json.loads(alias_names_raw)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(parsed, dict):
        return []

    candidates = []

    for key in ("alias", "equivalent_name"):
        value = parsed.get(key)
        if value and isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    aliases_list = parsed.get("aliases") or []
    if isinstance(aliases_list, list):
        candidates.extend(
            alias.strip()
            for alias in aliases_list
            if alias and isinstance(alias, str) and alias.strip()
        )

    return candidates


def fuzzy_search(
    query: str,
    limit: int = 5,
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

        # alias_names متخزنة كـ JSON — بنقارن على كل candidate لوحده
        for alias in _extract_alias_candidates(row.alias_names):
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