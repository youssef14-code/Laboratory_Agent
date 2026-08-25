"""
generate_preparations.py
------------------------------------------------------------
بيدور على كل التحاليل اللي عمود patient_instructions بتاعها
فاضي أو لسه القيمة الافتراضية ("لا يوجد تحضير خاص.")، وبيطلب من
Gemini يحدد التحضير المناسب فعليًا لكل تحليل بناءً على اسمه —
لو التحليل فعلاً مش محتاج تحضير، هيقول كده بردو (مش هيخترع حاجة).

طريقة التشغيل:
    python generate_preparations.py
    python generate_preparations.py --dry-run   (يعرض النتايج من غير ما يحفظ)
------------------------------------------------------------
"""

import sys
import os
import time
import argparse

project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models.models import LabService
from knowledge.utils import get_gemini_client

MODEL_NAME = "gemini-3.1-flash-lite"
DEFAULT_TEXT = "لا يوجد تحضير خاص."

SYSTEM_PROMPT = """
أنت مساعد طبي متخصص في تحضيرات التحاليل المعملية.

هدفك: تحديد تعليمات التحضير الصحيحة طبيًا للمريض قبل عمل تحليل معين،
بناءً على اسم التحليل بس.

قواعد مهمة:
- لو التحليل فعلاً محتاج تحضير معروف طبيًا (زي الصيام لساعات معينة،
  تجنب أطعمة معينة، التوقف عن دواء معين، جمع عينة في وقت محدد...)،
  اكتب التعليمات دي بوضوح واختصار بالعربي.
- لو التحليل فعلاً مش محتاج أي تحضير خاص (زي أغلب تحاليل الدم
  الروتينية)، اكتب بالظبط: "لا يوجد تحضير خاص."
- متخترعش تحضير غير موجود فعليًا في الممارسة الطبية المعروفة.
- رد بجملة أو جملتين بس، من غير أي مقدمات أو شرح إضافي.
"""


def generate_preparation(test_name: str) -> str:
    client_or_genai = get_gemini_client()
    prompt = f"اسم التحليل: {test_name}\n\nما هو التحضير المطلوب قبل عمل هذا التحليل؟"

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


def generate_with_backoff(test_name: str, max_attempts: int = 4) -> str | None:
    for attempt in range(1, max_attempts + 1):
        try:
            result = generate_preparation(test_name)
            if result:
                return result
        except Exception as e:
            wait = attempt * 2
            print(f"   ⚠️ فشلت المحاولة {attempt}/{max_attempts} لـ '{test_name}': {e}. إعادة بعد {wait}s...", flush=True)
            time.sleep(wait)
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate real preparation instructions for lab tests missing them.")
    parser.add_argument("--dry-run", action="store_true", help="يعرض النتايج من غير ما يحفظ في الداتابيز")
    args = parser.parse_args()

    with app.app_context():
        labs = LabService.query.filter(
            (LabService.patient_instructions.is_(None))
            | (LabService.patient_instructions == "")
            | (LabService.patient_instructions == DEFAULT_TEXT)
        ).all()

        total = len(labs)
        print(f"هيتم توليد تحضير لـ {total} تحليل...", flush=True)

        success, failed = 0, 0

        for idx, lab in enumerate(labs, start=1):
            instructions = generate_with_backoff(lab.name)

            if instructions is None:
                failed += 1
                print(f"[{idx}/{total}] [ERROR] فشل في '{lab.name}'", flush=True)
                continue

            print(f"[{idx}/{total}] {lab.name} -> {instructions}", flush=True)

            if not args.dry_run:
                lab.patient_instructions = instructions
                db.session.commit()

            success += 1
            time.sleep(0.6)  # rate limit pacing

    print("\n==========================================", flush=True)
    print("=== GENERATE PREPARATIONS COMPLETE ===", flush=True)
    print(f" Total:   {total}", flush=True)
    print(f" Success: {success}", flush=True)
    print(f" Failed:  {failed}", flush=True)
    if args.dry_run:
        print(" (dry-run: لسه مفيش حاجة اتحفظت في الداتابيز)", flush=True)
    print("==========================================", flush=True)


if __name__ == "__main__":
    main()
