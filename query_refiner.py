"""
query_refiner.py
------------------------------------------------------------
بياخد سؤال المستخدم زي ما هو (بأي صياغة، حتى لو فيه أكتر من
تحليل في نفس الجملة)، ويستخدم Gemini عشان يحوّله لقايمة
"refined queries" — كل واحدة فيها:
  - query: اسم التحليل أو الموضوع المستخرج (نضيف)
  - description: وصف قصير بيساعد الـ semantic search يفهم القصد
------------------------------------------------------------
"""

import json

from pydantic import BaseModel

from knowledge.utils import get_gemini_client

MODEL_NAME = "gemini-3.1-flash-lite"


class RefinedQuery(BaseModel):
    query: str
    description: str | None = None


SYSTEM_PROMPT = """
أنت مساعد بيفهم أسئلة المستخدمين عن التحاليل الطبية ويحولها لصيغة بحث نضيفة.

المستخدم ممكن يسأل بأي طريقة (عامية، فصحى، إنجليزي، أو خليط)، وممكن يسأل
عن أكتر من تحليل في نفس الجملة.

مهمتك: استخرج كل تحليل أو موضوع منفصل مذكور في السؤال، ولكل واحد رجّع:
  - query: اسم قصير ونضيف للتحليل أو الموضوع (زي ما هيتقال في معمل)
  - description: جملة قصيرة توضح قصد المستخدم (اختياري، ممكن تسيبها فاضية)

رجّع JSON array فقط (من غير أي نص زيادة أو ```)، بالشكل ده:
[
  {"query": "...", "description": "..."},
  {"query": "...", "description": "..."}
]

لو السؤال مش واضح أو مش عن تحليل معملي، رجّع array فيه عنصر واحد
بالـ query الأصلي زي ما هو.
"""


def refine_query(raw_query: str) -> list[RefinedQuery]:
    client_or_genai = get_gemini_client()
    prompt = f"سؤال المستخدم:\n{raw_query}"

    if hasattr(client_or_genai, "models"):
        response = client_or_genai.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={"system_instruction": SYSTEM_PROMPT},
        )
        text = response.text
    else:
        model = client_or_genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(prompt)
        text = response.text

    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]

    try:
        data = json.loads(text.strip())
        return [RefinedQuery(**item) for item in data]
    except Exception:
        # لو التوليد فشل أو رجّع شكل غير متوقع، استخدم السؤال الأصلي زي ما هو
        return [RefinedQuery(query=raw_query, description=None)]
