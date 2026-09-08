import json
import logging

from sqlalchemy import text
from rapidfuzz import fuzz

from knowledge.utils import main_session
from search.preprocess.normalize import normalize
from search.preprocess.ngram import ngram_similarity
from ..schemas import SearchResult

logger = logging.getLogger(__name__)

TABLE_NAME = "labservices"
MIN_SCORE = 0.45  # final score (0-1)


def _score_against(normalized_query: str, candidate: str) -> float:
    """بيحسب score واحد بين نص query متطبّع مسبقاً وأي نص مرشح خام (اسم أو alias أو keyword)."""
    try:
        normalized_candidate = normalize(candidate)
    except Exception as e:
        logger.warning("normalize failed for candidate %r: %s", candidate, e)
        return 0.0

    if not normalized_candidate:
        return 0.0

    try:
        rapid = max(
            fuzz.partial_ratio(normalized_query, normalized_candidate),
            fuzz.token_set_ratio(normalized_query, normalized_candidate),
        ) / 100

        ngram = ngram_similarity(normalized_query, normalized_candidate)
    except Exception as e:
        logger.warning(
            "scoring failed for query=%r candidate=%r: %s",
            normalized_query, normalized_candidate, e,
        )
        return 0.0

    return (rapid + ngram) / 2


def _extract_json_list_candidates(raw) -> list[str]:
    """استخراج قائمة النصوص الصالحة من JSON سواء كان List أو String."""
    if not raw:
        return []

    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("could not parse JSON candidates %r: %s", raw, e)
            return []

    if not isinstance(parsed, list):
        return []

    try:
        return [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    except Exception as e:
        logger.warning("could not normalize candidate list %r: %s", parsed, e)
        return []


def _build_query_candidates(query: str, aliases: list[str] | None, keywords: list[str] | None) -> list[str]:
    """تجميع وتطبيع النصوص الصالحة للبحث."""
    raw_candidates = ([query] if query else []) + list(aliases or []) + list(keywords or [])

    normalized = []
    for c in raw_candidates:
        if not c or not isinstance(c, str):
            continue
        try:
            n = normalize(c)
        except Exception as e:
            logger.warning("normalize failed for query candidate %r: %s", c, e)
            continue
        if n and n not in normalized:
            normalized.append(n)

    return normalized


def fuzzy_search(
    query: str,
    aliases: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 2,
) -> list[SearchResult]:

    # 1. تجهيز نصوص البحث الأساسية (الاسم والـ Aliases فقط بدون كلمات دلالية عامة)
    primary_query_candidates = _build_query_candidates(query, aliases, keywords=None)
    keyword_query_candidates = _build_query_candidates("", aliases=None, keywords=keywords)

    if not primary_query_candidates and not keyword_query_candidates:
        return []

    try:
        with main_session() as session:
            rows = session.execute(
                text(f"SELECT id, name, alias_names, keywords FROM {TABLE_NAME}")
            ).fetchall()
    except Exception as e:
        logger.error("fuzzy_search DB query failed: %s", e)
        return []

    scored = []

    for row in rows:
        try:
            # مرشحو الصف الأساسيون: الاسم الرسمي + أسماء الشهرة (Aliases) فقط
            primary_row_candidates = [row.name] + _extract_json_list_candidates(row.alias_names)

            # 🎯 المرحلة الأولى: مطابقة الأسماء والـ Aliases (تأخذ السكور الكامل 100%)
            best_score = 0.0
            for q_cand in primary_query_candidates:
                for r_cand in primary_row_candidates:
                    s = _score_against(q_cand, r_cand)
                    if s > best_score:
                        best_score = s

            # 🎯 المرحلة الثانية: لو لم نجد تطابقاً قوياً في الأسماء، نبحث في الكلمات الدلالية بوزن مخفض (70% كحد أقصى)
            if best_score < 0.85 and keyword_query_candidates:
                row_keywords = _extract_json_list_candidates(row.keywords)
                for q_k in keyword_query_candidates:
                    for r_k in row_keywords:
                        s_k = _score_against(q_k, r_k) * 0.70  # 👈 تخفيض وزن الكلمات العامة حتى لا تصل لـ 1.0
                        if s_k > best_score:
                            best_score = s_k

            if best_score >= MIN_SCORE:
                scored.append((row, best_score))

        except Exception as e:
            logger.warning("skipping row id=%s due to scoring error: %s", getattr(row, "id", "?"), e)
            continue

    scored.sort(key=lambda x: x[1], reverse=True)

    try:
        results = [
            SearchResult(
                id=row.id,
                name=row.name,
                score=round(final_score, 3),
                source="fuzzy",
            )
            for row, final_score in scored[:limit]
        ]
    except Exception as e:
        logger.error("failed to build SearchResult list: %s", e)
        return []

    return results