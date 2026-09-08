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


def build_search_text(name: str, description: str, keywords: list, aliases: list = None) -> str:
    """
    بيبني النص اللي هيتحول لـ vector في مرحلة الـ Semantic search بس.

    ملحوظة تصميم: name و aliases متعمّد استبعادهم من هنا، لأنهم بيتغطوا
    فعلياً في مراحل سابقة من الـ pipeline  
   (Fuzzy Search) قبل ما نوصل للـ semantic أصلاً. لو حطيناهم هنا كمان
    هيبقى تكرار مالوش داعي، والـ semantic المفروض يركز بس على المعنى
    الطبي (description + keywords).

    `name` و`aliases` باقيين كـ parameters اختيارية بس عشان أي كود قديم
    بينادي الدالة بيهم مايكسرش — بيتجاهلوا تماماً هنا.
    """
    keywords_str = ", ".join(keywords) if keywords else ""
    return (
        f"{description}\n"
        f"الكلمات المفتاحية: {keywords_str}"
    ).strip()


def generate_embedding(text: str, task_type: str = "retrieval_document") -> list[float]:
    """
    بيبعت النص لـ Gemini ويرجع vector طوله 768، متطبّع (normalized) عشان
    نقدر نقارن بينه وبين vectors تانية بالـ inner product بدل cosine كامل.

    task_type:
        - "retrieval_document" (default): للنصوص اللي بتتخزن في الـ FAISS
          index (search_text بتاع كل تحليل وقت الـ generation/rebuild).
        - "retrieval_query": لنص سؤال المستخدم وقت البحث الفعلي (semantic
          search). لازم يبقى مختلف عن الـ document عشان الموديل (المدرّب
          بطريقة asymmetric) يدي مطابقة أدق بين السؤال والمستندات.
    """
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type=task_type,
        output_dimensionality=EMBEDDING_DIM,
    )
    vec = np.array(result["embedding"], dtype="float32")

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec.tolist()