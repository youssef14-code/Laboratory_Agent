import os
from langchain_openai import ChatOpenAI

def get_gemini():
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY must be set."
        )

    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL"),
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        extra_body={"reasoning": {"effort": "medium"}},
        temperature=0.0,
    ) 