from .schemas import GeneratedKnowledge


def normalize_knowledge(data: GeneratedKnowledge, item_name: str) -> GeneratedKnowledge:

    data.alias_names.aliases = sorted(
        {
            x.strip()
            for x in data.alias_names.aliases
            if x and x.strip()
        }
    )

    data.keywords = sorted(
        {
            x.strip()
            for x in data.keywords
            if x and x.strip()
        }
    )

    data.description = data.description.strip()

    data.construct_search_text(item_name)

    return data
