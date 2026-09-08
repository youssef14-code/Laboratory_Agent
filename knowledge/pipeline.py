import logging
from .generator import generate_knowledge, regenerate_knowledge
from .schemas import (
    EntityType,
    GeneratedKnowledge,
    KnowledgeGenerationRequest,
)
from .updater import update_knowledge
from .normalizer import normalize_knowledge

# --- النسخة المبسطة الجديدة بدل knowledge.embedding / knowledge.vector_store ---
from .embedding import generate_embedding, build_search_text
from .vector_store import upsert_vector

logger = logging.getLogger(__name__)


def run_pre_approval_stage(
    request: KnowledgeGenerationRequest,
) -> GeneratedKnowledge:
    generated = generate_knowledge(request)
    generated = normalize_knowledge(generated, request.name)
    return generated


def regenerate(
    request: KnowledgeGenerationRequest,
    previous_output: GeneratedKnowledge,
    admin_feedback: str | None = None,
) -> GeneratedKnowledge:
    generated = regenerate_knowledge(
        request=request,
        previous_output=previous_output,
        admin_feedback=admin_feedback,
    )
    generated = normalize_knowledge(generated, request.name)
    return generated


def run_post_approval_stage(entity_id: int, entity_type: EntityType, name: str,
                             final_knowledge: GeneratedKnowledge) -> None:
    """
    Runs after the admin clicks "Approve":
        Update DB -> Generate Embedding -> Insert into Vector Database
    """
    # 1) تجهيز الداتا اللي هتتحفظ في MySQL/SQLite
    from .schemas import ApprovedKnowledge
    approved = ApprovedKnowledge(
        entity_id=entity_id,
        entity_type=entity_type,
        **final_knowledge.model_dump(),
    )
    update_knowledge(approved)

    # 2) بناء نص البحث وتوليد الـ embedding
    search_text = build_search_text(
        name=name,
        description=final_knowledge.description,
        keywords=final_knowledge.keywords,
        aliases=final_knowledge.alias_names,
    )
    embedding = generate_embedding(search_text)

    # 3) حفظ الـ embedding في FAISS، بـ entity_id نفسه كـ FAISS id مباشرة
    upsert_vector(lab_id=entity_id, name=name, embedding=embedding)

    logger.info("Knowledge pipeline complete for %s id=%s ('%s').", entity_type.value, entity_id, name)