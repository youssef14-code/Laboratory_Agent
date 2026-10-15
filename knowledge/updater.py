"""
updater.py
Saves approved knowledge into the main app DB (MySQL or SQLite).
Runs only AFTER the knowledge is final (create flow) — never before.
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
    Updates the lab row with description, keywords, alias_names,
    sample_type and search_text.

    Fields that are None / empty are SKIPPED, so an empty value (for example
    the default sample_type="") can never wipe data already in the row.
    keywords/alias_names are stored as JSON text.
    """
    table = TABLE_BY_TYPE[approved.entity_type]

    # Column names come from this fixed whitelist only (never user input),
    # so building the SET clause dynamically is safe.
    candidates = {
        "description": approved.description,
        "keywords": json.dumps(approved.keywords, ensure_ascii=False) if approved.keywords else None,
        "alias_names": json.dumps(approved.alias_names, ensure_ascii=False) if approved.alias_names else None,
        "sample_type": approved.sample_type,
        "search_text": approved.search_text,
    }
    values = {col: val for col, val in candidates.items() if val not in (None, "")}

    if not values:
        logger.info("No non-empty knowledge fields to save for %s id=%s.", table, approved.entity_id)
        return

    set_clause = ", ".join(f"{col} = :{col}" for col in values)

    with main_session() as session:
        session.execute(
            text(f"""
                UPDATE {table}
                SET {set_clause},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {**values, "id": approved.entity_id},
        )
    logger.info("Updated %s id=%s (%s).", table, approved.entity_id, ", ".join(values))