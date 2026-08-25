"""
vector_store.py (نسخة مبسطة)
------------------------------------------------------------
بيخزن ويدوّر على embeddings التحاليل في FAISS. بما إن عندنا نوع
واحد بس (lab)، بنستخدم id التحليل نفسه كـ FAISS id مباشرة —
مفيش داعي لأي hashing ولا تصنيف نوع.
------------------------------------------------------------
"""

import os
import pickle
import threading

import faiss
import numpy as np

FAISS_INDEX_PATH = "lads.faiss"
FAISS_METADATA_PATH = "labs_metadata.pkl"
EMBEDDING_DIM = 768

_index = None
_metadata = None   # dict بسيط: {lab_id: {"name": "..."}}
_lock = threading.Lock()


def _load():
    """بيحمّل الـ index والـ metadata من الديسك أول مرة بس، وبعدين بيفضلوا في الذاكرة."""
    global _index, _metadata
    if _index is not None:
        return
    with _lock:
        if _index is not None:
            return
        if os.path.exists(FAISS_INDEX_PATH):
            _index = faiss.read_index(FAISS_INDEX_PATH)
        else:
            # IndexFlatIP = بيقارن الـ vectors بـ inner product (= cosine similarity لأنها متطبّعة)
            # IndexIDMap2 = بيسمحلنا نربط كل vector بـ ID مخصص (id التحليل) بدل 0,1,2,3...
            _index = faiss.IndexIDMap2(faiss.IndexFlatIP(EMBEDDING_DIM))

        if os.path.exists(FAISS_METADATA_PATH):
            with open(FAISS_METADATA_PATH, "rb") as f:
                _metadata = pickle.load(f)
        else:
            _metadata = {}


def _save():
    """بيحفظ الـ index والـ metadata على الديسك عشان متضيعش لو السيرفر اتقفل."""
    faiss.write_index(_index, FAISS_INDEX_PATH)
    with open(FAISS_METADATA_PATH, "wb") as f:
        pickle.dump(_metadata, f)


def upsert_vector(lab_id: int, name: str, embedding: list[float]) -> None:
    """بيضيف embedding تحليل جديد، أو يستبدل القديم لو التحليل ده كان موجود بالفعل."""
    _load()
    vec = np.array(embedding, dtype="float32").reshape(1, -1)

    with _lock:
        if lab_id in _metadata:
            # التحليل ده كان موجود قبل كده -> شيل الـ vector القديم الأول
            _index.remove_ids(np.array([lab_id], dtype="int64"))

        _index.add_with_ids(vec, np.array([lab_id], dtype="int64"))
        _metadata[lab_id] = {"name": name}
        _save()


def delete_vector(lab_id: int) -> None:
    """بيشيل embedding تحليل اتمسح من الداتابيز."""
    _load()
    with _lock:
        if lab_id in _metadata:
            _index.remove_ids(np.array([lab_id], dtype="int64"))
            del _metadata[lab_id]
            _save()


def search(query_embedding: list[float], k: int = 5) -> list[dict]:
    """بيرجع أقرب k تحاليل لـ query_embedding، مرتبين من الأقرب للأبعد."""
    _load()
    vec = np.array(query_embedding, dtype="float32").reshape(1, -1)
    scores, ids = _index.search(vec, k)

    results = []
    for score, lab_id in zip(scores[0], ids[0]):
        if lab_id == -1:   # يعني مفيش نتيجة في المكان ده (الجدول أصغر من k)
            continue
        meta = _metadata.get(int(lab_id), {})
        results.append({
            "id": int(lab_id),
            "name": meta.get("name"),
            "score": float(score),
        })
    return results