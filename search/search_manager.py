from search.engines.fuzzy_search import fuzzy_search
from search.engines.semantic_search import semantic_search
from search.ranking.deduplicate import remove_duplicates


def run_search(refined_queries):

    all_results = []

    for item in refined_queries:

        fuzzy_results = fuzzy_search(
            query=item.query,
            aliases=item.aliases,
            keywords=item.keywords,
            limit=2,
        )

        semantic_results = semantic_search(
            query=item.query,
            keywords=item.keywords,
            description=item.description,
            limit=3,
        )

        all_results.extend(fuzzy_results)
        all_results.extend(semantic_results)

    if not all_results:
        return {
            "results": [],
            "top_score": 0.0,
        }

    results = remove_duplicates(all_results)

    results.sort(key=lambda x: x.score, reverse=True)

    return {
        "results": results,
        "top_score": results[0].score if results else 0.0,
    }