"""
schemas.py
Pydantic models used to validate data at every stage of the pipeline.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    LAB = "lab"


class KnowledgeGenerationRequest(BaseModel):
    name: str
    patient_instructions: Optional[str] = None
    duration: Optional[str] = None
    price: Optional[float] = None
    entity_type: EntityType = EntityType.LAB
    entity_id: Optional[int] = None


class AliasNames(BaseModel):
    alias: str = ""
    measurement: str = ""
    equivalent_name: str = ""
    aliases: List[str] = Field(default_factory=list)


class GeneratedKnowledge(BaseModel):
    description: str
    alias_names: AliasNames
    sample_type: str = ""
    keywords: List[str] = Field(default_factory=list)
    search_text: Optional[str] = ""

    def construct_search_text(self, item_name: str) -> str:
        aliases_str = ", ".join(self.alias_names.aliases)
        keywords_str = ", ".join(self.keywords)

        self.search_text = (
            f"{item_name}\n"
            f"{self.description}\n"
            f"الاسم البديل الأساسي: {self.alias_names.alias}\n"
            f"المرادفات والأسماء البديلة: {aliases_str}\n"
            f"الكلمات المفتاحية: {keywords_str}"
        )

        return self.search_text


class ApprovedKnowledge(GeneratedKnowledge):
    entity_id: int
    entity_type: EntityType

    # VectorMetadata اتشالت — النسخة المبسطة (vector_store_simple.py)
    # بتاخد lab_id و name كـ arguments عادية بدل ما تحتاج object منفصل.