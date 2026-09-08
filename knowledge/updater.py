"""
updater.py
Saves approved knowledge into the main app DB (MySQL أو SQLite).
Runs only AFTER administrator approval — never before.
"""

import json
import logging

from sqlalchemy import text

from .schemas import ApprovedKnowledge, EntityType
from .utils import main_session

logger = logging.getLogger(__name__)

TABLE_BY_TYPE = {
    EntityType.LAB: "labservices",
}


def update_knowledge(approved: ApprovedKnowledge) -> None:
    """
    Updates the Lab/Bundle row with description, keywords, alias_names,
    sample_type, and search_text. keywords/alias_names are stored as JSON
    text columns (JSON MySQL / TEXT في SQLite).
    """
    table = TABLE_BY_TYPE[approved.entity_type]

    with main_session() as session:
        session.execute(
            text(f"""
                UPDATE {table}
                SET description = :description,
                    keywords = :keywords,
                    alias_names = :alias_names,
                    sample_type = :sample_type,
                    search_text = :search_text,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {
                "description": approved.description,
                "keywords": json.dumps(approved.keywords, ensure_ascii=False),
                # alias_names بقى list[str] عادي (مش AliasNames object)، فمفيش
                # داعي لـ .model_dump() -- json.dumps مباشرة على الـ list.
                "alias_names": json.dumps(approved.alias_names, ensure_ascii=False),
                "sample_type": approved.sample_type,
                "search_text": approved.search_text,
                "id": approved.entity_id,
            },
        )
    logger.info("Updated %s id=%s with approved knowledge.", table, approved.entity_id)