import os
from langchain_openai import ChatOpenAI

def get_gemini():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in the environment variables.")
    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL"),
        api_key=api_key,
        use_responses_api=True,
        reasoning={"effort": "medium"},
        temperature=0.0,
    )    