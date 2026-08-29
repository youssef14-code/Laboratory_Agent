from pydantic import BaseModel


class SearchResult(BaseModel):
    id: int
    name: str
    score: float          # normalized 0.0 - 1.0, always, regardless of method
    source: str            #  "fuzzy" | "semantic"
