from sqlalchemy import bindparam, text

from knowledge.utils import main_session
from search.schemas import SearchResult
import logging
logger = logging.getLogger(__name__)

TABLE_NAME = "labservices"


def _fetch_rows(results: list[SearchResult]) -> dict:

    ids = [result.id for result in results]

    if not ids:
        return {}

    query = text(f"""
        SELECT
            id,
            name,
            alias_names,
            keywords,
            description,
            price,
            sample_type,
            durations,
            patient_instructions
        FROM {TABLE_NAME}
        WHERE id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    with main_session() as session:
        result_rows = session.execute(query, {"ids": ids}).mappings()
        rows = {row["id"]: dict(row) for row in result_rows}

    return rows


def build_context(results: list[SearchResult]) -> str:

    rows = _fetch_rows(results)

    sections = []

    for result in results:

        row = rows.get(result.id)

        if row is None:
            continue

        block = [f"Name: {row['name']}"]

        # ✅ Include alias_names so the LLM knows e.g. INR is an alias for P.T
        if row.get("alias_names"):
            aliases = row["alias_names"]
            if isinstance(aliases, str):
                import json
                try:
                    aliases = json.loads(aliases)
                except Exception:
                    aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            if aliases:
                block.append(f"Also known as (aliases): {', '.join(str(a) for a in aliases)}")

        # ✅ Include keywords for better concept matching
        if row.get("keywords"):
            keywords = row["keywords"]
            if isinstance(keywords, str):
                import json
                try:
                    keywords = json.loads(keywords)
                except Exception:
                    keywords = [k.strip() for k in keywords.split(",") if k.strip()]
            if keywords:
                block.append(f"Keywords: {', '.join(str(k) for k in keywords)}")

        if row.get("description"):
            block.append(f"Description: {row['description']}")

        if row.get("price") is not None:
            block.append(f"Price: {row['price']}")

        if row.get("sample_type"):
            block.append(f"Sample Type: {row['sample_type']}")

        if row.get("durations"):
            block.append(f"Duration: {row['durations']}")

        if row.get("patient_instructions"):
            block.append(f"Patient Instructions: {row['patient_instructions']}")

        sections.append("\n".join(block))
        logger.info(f"[build_context] Built context for result ID {result.id}: {block}")
        logger.debug(f"[build_context] Current sections: {sections}")

    return "\n\n" + "\n\n".join(sections)