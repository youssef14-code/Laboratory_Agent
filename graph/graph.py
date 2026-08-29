from langgraph.graph import END, StateGraph

from graph.nodes.complaint_node import complaint_node
from graph.nodes.direct_node import direct_node
from graph.nodes.homevisit_node import visit_node
from graph.nodes.inquiry_node import inquiry_node
from graph.nodes.intent_node import intent_node
from graph.nodes.rag_node import rag_node
from graph.nodes.labresults_node import result_node  
from graph.state import AgentState

__agent_graph = None


def route_intent(state: AgentState):
    """راوتر بعد intent_node — يوجه للنود المناسبة."""
    intent = state.get("intent", "direct")

    # لو النية كانت نتائج، نحولها لـ direct مؤقتاً
    if intent == "labresults":
        return "direct"

    return intent


def route_after_rag(state: AgentState):
    """راوتر منفصل بعد rag_node — يقبل فقط visit أو inquiry."""
    intent = state.get("intent")
    if intent not in ("visit", "inquiry"):
        raise ValueError(
            f"route_after_rag: unexpected intent '{intent}' after rag_node — "
            f"expected 'visit' or 'inquiry'."
        )
    return intent


def build_graph():

    graph = StateGraph(AgentState)

    # 1. Nodes
    graph.add_node("intent", intent_node)
    graph.add_node("rag", rag_node)
    graph.add_node("visit", visit_node)
    graph.add_node("complaint", complaint_node)
    graph.add_node("inquiry", inquiry_node)
    graph.add_node("direct", direct_node)
    graph.add_node("labresults", result_node)

    # 2. Entry Point
    graph.set_entry_point("intent")

    # 3. Intent Routing
    graph.add_conditional_edges(
        "intent",
        route_intent,
        {
            "visit": "rag",
            "inquiry": "rag",
            "complaint": "complaint",
            "direct": "direct",
            "labresults": "labresults",
        },
    )

    # 4. After RAG Routing
    graph.add_conditional_edges(
        "rag",
        route_after_rag,
        {
            "visit": "visit",
            "inquiry": "inquiry",
        },
    )

    # 5. End Edges
    graph.add_edge("visit", END)
    graph.add_edge("complaint", END)
    graph.add_edge("inquiry", END)
    graph.add_edge("direct", END)
    graph.add_edge("labresults", END)
    return graph.compile()


def get_agent_graph():
    global __agent_graph

    if __agent_graph is None:
        __agent_graph = build_graph()

    return __agent_graph