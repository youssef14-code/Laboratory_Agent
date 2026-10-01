import os
from langchain_google_genai import ChatGoogleGenerativeAI

def get_gemini():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in the environment variables.")
    return ChatGoogleGenerativeAI(
        model=os.environ.get("OPENAI_MODEL"),
        api_key=api_key,
        use_responses_api=True,
        reasoning={"effort": "low"},
        temperature=0.0,
    )   