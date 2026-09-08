"""
test_semantic.py
------------------------------------------------------------
سكريبت لتجربة semantic_search وعرض:
- نص الـ query الأصلي
- search_text اللي اتبنى وده اللي اتعمله embedding فعلياً
- كل نتيجة رجعت (id, name, score) + description و keywords بتاعتها
  من الداتابيز، عشان تتأكد بعينك إن المطابقة منطقية.

طريقة التشغيل (من جوه مجلد المشروع Laboratory_Agent):
    python test_semantic.py "تحليل الحمل"
    python test_semantic.py "غدة درقية"
    python test_semantic.py                # يشغل كذا مثال جاهز
------------------------------------------------------------
"""

import sys
import os
import logging

project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

# عشان نشوف الـ logger.info بتاع search_text اللي حطيناه جوه semantic_search.py
logging.basicConfig(level=logging.INFO, format="%(message)s")

from app import app
from models.models import LabService
from search.engines.semantic_search import semantic_search


DEFAULT_QUERIES = [
    "تحليل الحمل",
    "غدة درقية مناعة",
    "سكر في البول",
    "إنزيم البنكرياس",
    "lyzemei",
]


def run_query(q: str):
    print(f"\n{'=' * 60}")
    print(f"🔍 Query: '{q}'")
    print("=" * 60)

    try:
        results = semantic_search(q)
    except Exception as e:
        print(f"   ❌ semantic_search failed for '{q}': {e}")
        return

    if not results:
        print("   (no results)")
        return

    for r in results:
        try:
            lab = LabService.query.get(r.id)
            description = lab.description if lab else None
            keywords = lab.keywords if lab else None
        except Exception as e:
            print(f"   ⚠️ Could not fetch details for id={r.id}: {e}")
            description, keywords = None, None

        print(f"\n   ▶ id={r.id:<4} score={r.score:<6} name={r.name}")
        print(f"     description : {description}")
        print(f"     keywords    : {keywords}")


def main():
    queries = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_QUERIES

    try:
        with app.app_context():
            for q in queries:
                run_query(q)
    except Exception as e:
        print(f"\n❌ Fatal error while running test_semantic: {e}")


if __name__ == "__main__":
    main()
