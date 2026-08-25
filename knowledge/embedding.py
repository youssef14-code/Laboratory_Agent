"""
embedding.py (نسخة مبسطة)
------------------------------------------------------------
بيحول نص التحليل لـ vector (قايمة أرقام طولها 768) باستخدام Gemini.
------------------------------------------------------------
"""

import os
import numpy as np
import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

EMBEDDING_MODEL = "models/gemini-embedding-2"
EMBEDDING_DIM = 768


def build_search_text(name: str, description: str, keywords: list, aliases: list) -> str:
    """بيجمع كل حاجة عن التحليل في نص واحد، وده اللي هيتحول لـ vector."""
    keywords_str = ", ".join(keywords) if keywords else ""
    aliases_str = ", ".join(aliases) if aliases else ""
    return (
        f"{name}\n"
        f"{description}\n"
        f"المرادفات: {aliases_str}\n"
        f"الكلمات المفتاحية: {keywords_str}"
    ).strip()


def generate_embedding(text: str) -> list[float]:
    """
    بيبعت النص لـ Gemini ويرجع vector طوله 768، متطبّع (normalized) عشان
    نقدر نقارن بينه وبين vectors تانية بالـ inner product بدل cosine كامل.
    """
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="retrieval_document",
        output_dimensionality=EMBEDDING_DIM,
    )
    vec = np.array(result["embedding"], dtype="float32")

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec.tolist()