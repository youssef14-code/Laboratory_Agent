""" from graph.state import AgentState
from rag.context_builder import build_context
from search.search_manager import run_search


def rag_node(state: AgentState):

    refined_queries = state.get("refined_queries", [])

    retrieval_results = []

    for refined_query in refined_queries:

        search = run_search([refined_query])

        retrieval_results.append(
            {
                "query": refined_query.query,
                "results": search["results"],
                "top_score": search["top_score"],
            }
        )

    context = build_context(retrieval_results)

    return {
        "rag_context": context,
        "search_results": retrieval_results,
    } """