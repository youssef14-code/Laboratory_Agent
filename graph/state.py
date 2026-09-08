from typing import Any, TypedDict, Optional

class AgentState(TypedDict):

    # platform
    page_id: Optional[str]
    sender_id: Optional[str]
    platform_id: Optional[int]
    platform_name: Optional[str]
    laboratory_id: Optional[int]
    branch_id: Optional[int]


    # conversation
    user_message: str
    response: Optional[str]

    # routing
    intent: Optional[str]
    refined_queries: Optional[list]

   
    # memory
    summary: Optional[str]
    last_bot_message: Optional[str]
    chat_history: Optional[str]
    

    # flags
   
    visit_saved: Optional[bool]
    complaint_saved: Optional[bool]
    inquiry_saved: Optional[bool]
    labresults_saved: Optional[bool]
    
    
    
    laboratory_id: Optional[int]
    branch_id: Optional[int]   

    # usage
    intent_usage: Optional[dict]
    retrieval_usage: Optional[dict]
    booking_usage: Optional[dict]
    complaint_usage: Optional[dict]
    inquiry_usage: Optional[dict]
    direct_usage: Optional[dict]
    labresults_usage: Optional[dict]

    visit_reference: Optional[str]
    booking_pdf: Optional[bytes]
    booking_image: Optional[bytes]  # 👈 أضف هذا السطر


    rag_context: Optional[str]
    search_results: Optional[list[Any]]
    top_score: Optional[float]
    
    # timings
    node_timings: Optional[dict[str, float]]