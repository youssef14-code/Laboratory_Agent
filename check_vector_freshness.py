"""
check_vector_freshness.py
------------------------------------------------------------
بيتأكد إن الـ vector المخزّن فعلياً في الـ FAISS لتحليل معين
بيمثل الـ description/keywords الحاليين المخزّنين في الداتابيز،
مش نسخة قديمة/مختلفة اتخزنت في محاولة approve سابقة.

طريقة التشغيل:
    python check_vector_freshness.py 472
------------------------------------------------------------
"""

import sys
import os
import numpy as np

project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app
from models.models import LabService
import knowledge.vector_store as vs
from knowledge.embedding import generate_embedding, build_search_text


def main():
    if len(sys.argv) < 2:
        print("استخدام: python check_vector_freshness.py <lab_id>")
        return

    lab_id = int(sys.argv[1])

    with app.app_context():
        lab = LabService.query.get(lab_id)
        if not lab:
            print(f"❌ lab_id={lab_id} مش موجود في الداتابيز خالص.")
            return

        print(f"📄 البيانات الحالية في الداتابيز لـ id={lab_id} ('{lab.name}'):")
        print(f"   description : {lab.description}")
        print(f"   keywords    : {lab.keywords}")
        print(f"   search_text (column) : {lab.search_text}")

        # 1) الـ vector المخزّن فعلياً في الـ FAISS
        vs._load()
        if lab_id not in vs._metadata:
            print(f"\n❌ lab_id={lab_id} مش موجود في الـ metadata خالص.")
            return

        stored_vec = vs._index.reconstruct(lab_id)
        stored_vec = np.array(stored_vec, dtype="float32")

        # 2) embedding جديد "طازة" من البيانات الحالية في الداتابيز
        fresh_search_text = build_search_text(
            name=lab.name,
            description=lab.description or "",
            keywords=lab.keywords or [],
        )
        print(f"\n🆕 search_text لو بنيناه دلوقتي من بيانات الداتابيز الحالية:\n{fresh_search_text}")

        fresh_vec = np.array(generate_embedding(fresh_search_text), dtype="float32")

        # 3) المقارنة - الاتنين متطبّعين (normalized)، فـ dot product = cosine similarity
        similarity = float(np.dot(stored_vec, fresh_vec))

        print(f"\n📊 التشابه بين الـ vector المخزّن في FAISS والـ embedding الطازة: {similarity:.4f}")

        if similarity > 0.98:
            print("✅ الـ vector المخزّن مطابق فعلياً للبيانات الحالية — مفيش مشكلة staleness.")
        else:
            print("⚠️ فيه اختلاف واضح — الـ vector المخزّن في FAISS بيمثل نص مختلف عن البيانات الحالية في الداتابيز!")


if __name__ == "__main__":
    main()
