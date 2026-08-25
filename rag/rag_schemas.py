from pydantic import BaseModel

from search.schemas import SearchResult


class RetrievalResult(BaseModel):
    results: list[SearchResult]
    context: str
    top_score: float