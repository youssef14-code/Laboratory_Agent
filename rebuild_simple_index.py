"""
rebuild_simple_index.py
------------------------------------------------------------
بيمسح lads.faiss و labs_metadata.pkl القديمين (اللي مبنيين
بمنطق الـ hashing القديم)، وبيعيد بنائهم من الصفر من جدول
labservices، باستخدام lab_id نفسه كـ FAISS id مباشرة
(نفس منطق vector_store_simple.py الجديد).

طريقة التشغيل:
    python rebuild_simple_index.py
------------------------------------------------------------
"""

import os
import sys
import time

project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models.models import LabService

from knowledge.embedding import generate_embedding, build_search_text
from knowledge.vector_store import FAISS_INDEX_PATH, FAISS_METADATA_PATH, upsert_vector


def parse_json_field(value) -> list[str]:
    """alias_names و keywords متخزنين كـ JSON list في MySQL (db.JSON) -
    SQLAlchemy بيرجعهم كـ list بايثون جاهز، مش نص محتاج parsing."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    return []


def main():
    # 1) مسح الملفات القديمة (المبنية بمنطق الـ hashing القديم)
    for path in (FAISS_INDEX_PATH, FAISS_METADATA_PATH):
        if os.path.exists(path):
            os.remove(path)
            print(f"اتمسح الملف القديم: {path}", flush=True)

    with app.app_context():
        labs = LabService.query.filter(LabService.is_active.is_(True)).all()
        total = len(labs)
        print(f"هيتم إعادة فهرسة {total} تحليل...", flush=True)

        success, failed = 0, 0

        for idx, lab in enumerate(labs, start=1):
            try:
                keywords = parse_json_field(lab.keywords)
                aliases = parse_json_field(lab.alias_names)

                text = build_search_text(
                    name=lab.name,
                    description=lab.description or "",
                    keywords=keywords,
                    aliases=aliases,
                )

                embedding = generate_embedding(text)
                upsert_vector(lab_id=lab.id, name=lab.name, embedding=embedding)

                success += 1
                print(f"[{idx}/{total}] [OK] {lab.name} (id={lab.id})", flush=True)

            except Exception as e:
                failed += 1
                print(f"[{idx}/{total}] [ERROR] فشل في '{lab.name}': {e}", flush=True)

            time.sleep(0.2)   # بريك بسيط عشان الـ rate limit

    print("\n==========================================", flush=True)
    print("=== REBUILD COMPLETE ===", flush=True)
    print(f" Success: {success}", flush=True)
    print(f" Failed:  {failed}", flush=True)
    print("==========================================", flush=True)


if __name__ == "__main__":
    main()