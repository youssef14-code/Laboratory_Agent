import time
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

def timed_node(node_name: str, node_func):
    """دالة تغليف تقيس زمن تنفيذ النود بدقة الميلي ثانية."""
    def wrapper(state: AgentState) -> dict:
        t0 = time.perf_counter()
        output = node_func(state)
        elapsed = time.perf_counter() - t0
        
        # حفظ وحساب زمن كل نود
        timings = dict(state.get("node_timings") or {})
        timings[node_name] = round(elapsed, 3)
        
        if isinstance(output, dict):
            output["node_timings"] = timings
        return output
    return wrapper


def route_intent(state: AgentState):
    """
    راوتر بعد intent_node — يوجه للنود المناسبة.

    - inquiry: بيمر دايماً بالـ RAG (محتاج معلومات تحاليل عشان يجاوب).
    - visit: بيمر بالـ RAG بس لو فيه refined_queries (يعني العميل ذكر
      اسم تحليل معين مع طلب الحجز، فمحتاجين السعر/التحضير). لو مفيش أي
      تحليل مذكور في الرسالة دي (زي "عايز احجز" لوحدها، أو "اسمي يوسف"
      أثناء جمع البيانات)، بيروح visit_node على طول من غير أي بحث.
    - labresults: بتروح لـ node بتاعتها مباشرة (مش direct — دي اللي كانت
      المشكلة قبل كده).
    - complaint/direct: زي ما هما.
    """
    intent = state.get("intent", "direct")

    if intent == "visit":
        refined_queries = state.get("refined_queries") or []
        if not refined_queries:
            return "visit_direct"
        return "rag"

    if intent == "inquiry":
        return "rag"

    return intent


def route_after_rag(state: AgentState):
    """راوتر منفصل بعد rag_node — يقبل فقط visit أو inquiry."""
    intent = state.get("intent")
    if intent not in ("visit", "inquiry"):
        return "visit"  # fallback — should never happen
    return intent


def build_graph():

    graph = StateGraph(AgentState)

    # 1. إضافة النودز مع القياس الزمني التلقائي
    graph.add_node("intent", timed_node("intent_node", intent_node))
    graph.add_node("rag", timed_node("rag_node", rag_node))
    graph.add_node("visit", timed_node("visit_node", visit_node))
    graph.add_node("complaint", timed_node("complaint_node", complaint_node))
    graph.add_node("inquiry", timed_node("inquiry_node", inquiry_node))
    graph.add_node("direct", timed_node("direct_node", direct_node))
    graph.add_node("labresults", timed_node("labresults_node", result_node))

    # 2. Entry Point
    graph.set_entry_point("intent")

    # 3. Intent Routing
    graph.add_conditional_edges(
        "intent",
        route_intent,
        {
            "rag": "rag",              # inquiry، أو visit ومعاه refined_queries
            "visit_direct": "visit",   # visit من غير أي تحليل مذكور -- تخطي RAG
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