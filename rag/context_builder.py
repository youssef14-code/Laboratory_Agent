from sqlalchemy import bindparam, text

from knowledge.utils import main_session
from search.schemas import SearchResult

TABLE_NAME = "labservices"


def _fetch_rows(results: list[SearchResult]) -> dict:

    ids = [result.id for result in results]

    if not ids:
        return {}

    query = text(f"""
        SELECT
            id,
            name,
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

    return "\n\n" + "\n\n".join(sections)