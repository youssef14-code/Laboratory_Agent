"""
answer_generator.py
------------------------------------------------------------
بياخد سؤال المستخدم الأصلي + context الناتج من الـ RAG pipeline،
ويطلب من Gemini يرد على المستخدم بناءً على الـ context ده بس.
------------------------------------------------------------
"""

from knowledge.utils import get_gemini_client

MODEL_NAME = "gemini-3.1-flash-lite"

SYSTEM_PROMPT = """
أنت مساعد معمل تحاليل طبية. جاوب على سؤال المستخدم بناءً على المعلومات
الموجودة في الـ Context بس تحت. متخترعش أي معلومة مش موجودة فيه.

لو الـ Context فاضي أو مفيهوش إجابة للسؤال، قول للمستخدم بوضوح إنك
مش لاقي التحليل ده عندك، ومتحاولش تخمّن.

رد بالعربي، بأسلوب واضح ومباشر.
"""


def generate_answer(user_query: str, context: str) -> str:
    client_or_genai = get_gemini_client()

    prompt = f"Context:\n{context}\n\nسؤال المستخدم:\n{user_query}"

    if hasattr(client_or_genai, "models"):
        response = client_or_genai.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={"system_instruction": SYSTEM_PROMPT},
        )
        return response.text.strip()

    model = client_or_genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)
    response = model.generate_content(prompt)
    return response.text.strip()
