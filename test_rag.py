"""
test_rag.py
------------------------------------------------------------
سكريبت تفاعلي لاختبار الـ RAG كامل:

  1) المستخدم يكتب سؤال بأي صياغة.
  2) query_refiner.refine_query() يفكّك السؤال لـ refined queries.
  3) search_manager.run_search() يشغّل fuzzy + semantic search.
  4) context_builder.build_context() يبني نص السياق من النتايج.
  5) answer_generator.generate_answer() يولّد رد نهائي بـ Gemini.

طريقة التشغيل:
    python test_rag.py
------------------------------------------------------------
"""

import sys
import os

project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app  # عشان Flask app context لو حابب تستخدمه، اختياري هنا

from query_refiner import refine_query
from search.search_manager import run_search
from rag.context_builder import build_context
from answer_generator import generate_answer


def run_once(user_query: str):
    print("\n" + "=" * 60)
    print(f"سؤال المستخدم: {user_query}")
    print("=" * 60)

    # 1) Refine
    refined_queries = refine_query(user_query)
    print("\n[1] Refined Queries:")
    for rq in refined_queries:
        print(f"   - query: {rq.query!r} | description: {rq.description!r}")

    # 2) Search (fuzzy + semantic)
    search_output = run_search(refined_queries)
    results = search_output["results"]
    top_score = search_output["top_score"]

    print(f"\n[2] Search Results (top_score={top_score}):")
    if not results:
        print("   (مفيش نتايج)")
    for r in results:
        print(f"   - {r.name} (id={r.id}, score={r.score}, source={r.source})")

    # 3) Build context
    context = build_context(results)
    print("\n[3] Context اللي هيتبعت للـ LLM:")
    print(context if context.strip() else "   (فاضي)")

    # 4) Generate final answer
    answer = generate_answer(user_query, context)
    print("\n[4] رد الـ LLM النهائي:")
    print(answer)
    print("=" * 60 + "\n")


def main():
    print("=== RAG Test — اكتب 'exit' للخروج ===\n")

    with app.app_context():
        while True:
            user_query = input("اكتب سؤالك: ").strip()
            if user_query.lower() in ("exit", "quit", "خروج"):
                break
            if not user_query:
                continue
            run_once(user_query)


if __name__ == "__main__":
    main()
