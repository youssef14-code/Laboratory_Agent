"""
add_new_labtests.py
------------------------------------------------------------
بيضيف تحاليل جديدة (من إكسل فيه على الأقل Test + Price) لنفس المعمل
الموجود، من غير أي reset للجدول — بيتخطى أي تحليل موجود بالاسم بالفعل.

نفس أسلوب rebuild_knowledge.py بالظبط، بس من غير خطوة الـ reset،
وبيستخدم النسخة المبسطة الجديدة (embedding_simple / vector_store_simple)
بدل knowledge.embedding / knowledge.vector_store القديمين.

المدة (duration) والتحضير (patient_instructions):
- لو موجودين في الإكسل، بناخدهم كما هما (أولوية الإكسل).
- لو مش موجودين، جيميناي بيولّدهم بناءً على نوع التحليل نفسه.
- لو الاتنين مش متاحين (إكسل ولا جيميناي)، بنستخدم قيمة افتراضية أخيرة.

طريقة التشغيل:
    python add_new_labtests.py "new_tests.xlsx"
    python add_new_labtests.py "new_tests.xlsx" --sheet 0
------------------------------------------------------------
"""

import sys
import os
import time
import argparse
import pandas as pd

# Ensure project root is on the path
project_dir = os.path.abspath(os.path.dirname(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models.models import Laboratory, LabService
from knowledge.schemas import KnowledgeGenerationRequest, EntityType
from knowledge.generator import generate_knowledge

# --- النسخة المبسطة الجديدة بدل knowledge.embedding / knowledge.vector_store ---
from knowledge.embedding import generate_embedding, build_search_text
from knowledge.vector_store import upsert_vector

DEFAULT_EXCEL_NAME = "Price_List_2026 - Copy.xlsx"

# فولباك أخير بس لو الإكسل فاضي وجيميناي كمان فشل يولد قيمة
FALLBACK_DURATION = "24-48 ساعة"
FALLBACK_INSTRUCTIONS = "لا يوجد تحضير خاص لهذا التحليل."


# ══════════════════════════════════════════════════════════════════════════
# Helpers (نفس اللي في rebuild_knowledge.py بالظبط)
# ══════════════════════════════════════════════════════════════════════════

def clean_value(val):
    if pd.isna(val) or val is None:
        return ""
    val_str = str(val).strip()
    return "" if val_str.lower() in ["nan", "none", "n/a", "null"] else val_str


def clean_price(val):
    try:
        if pd.isna(val) or val is None:
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def get_field(obj, *names, default=None):
    """Try several possible attribute names on the generated-knowledge object."""
    for n in names:
        if hasattr(obj, n):
            val = getattr(obj, n)
            if val:
                return val
    return default


def generate_knowledge_with_backoff(req, max_attempts=5):
    for attempt in range(1, max_attempts + 1):
        try:
            gen = generate_knowledge(req)
            desc = get_field(gen, "description", default="")
            if gen and desc and "للمساعدة في التشخيص الطبي وتقييم الوظائف الحيوية" not in desc:
                return gen
        except Exception as e:
            wait = attempt * 2
            print(f"   ⚠️ API rate limit/error (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait}s...", flush=True)
            time.sleep(wait)

    try:
        return generate_knowledge(req)
    except Exception as e:
        print(f"   ❌ Failed to generate knowledge after {max_attempts} attempts: {e}", flush=True)
        return None


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Add new lab tests from an Excel file WITHOUT resetting the DB.")
    parser.add_argument("excel_path", nargs="?", default=None, help="Path to the new tests .xlsx file")
    parser.add_argument("--sheet", default=0, help="Sheet name or index to read (default: first sheet)")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N unique rows (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Generate knowledge only — no DB insert, no vector upsert")
    args = parser.parse_args()

    excel_path = args.excel_path or os.path.join(project_dir, DEFAULT_EXCEL_NAME)

    print("=== STARTING: ADD NEW LAB TESTS (NO RESET) ===", flush=True)
    if not os.path.exists(excel_path):
        print(f"Error: File '{excel_path}' not found!", flush=True)
        print("Pass the correct path as an argument, e.g.:", flush=True)
        print(f'  python {os.path.basename(__file__)} "Price_List_2026 - Copy.xlsx"', flush=True)
        return

    with app.app_context():
        lab_org = Laboratory.query.first()
        if not lab_org:
            # الموديل مفهوش عمود address، بس name و info
            lab_org = Laboratory(id=1, name="معامل د\\ماجد صفوت شاكر", info="معمل تحاليل")
            db.session.add(lab_org)
            db.session.commit()
        lab_org_id = lab_org.id

        # كل الأسماء الموجودة بالفعل عشان نتخطاها
        existing_names = {n for (n,) in db.session.query(LabService.name).all()}
        print(f"Found {len(existing_names)} tests already in DB — these will be skipped.", flush=True)

    df = pd.read_excel(excel_path, sheet_name=args.sheet)

    # Extract unique tests, preserving order
    unique_rows = []
    seen = set()
    for _, row in df.iterrows():
        name = clean_value(row.get("Test Name") or row.get("Test") or row.get("name") or row.get("Name"))
        if name and name not in seen:
            seen.add(name)
            unique_rows.append(row)

    if args.limit is not None:
        unique_rows = unique_rows[:args.limit]

    total_tests = len(unique_rows)
    print(f"Loaded {total_tests} unique lab tests from Excel.", flush=True)
    if args.dry_run:
        print("*** DRY RUN MODE: nothing will be saved to the DB or the FAISS index ***", flush=True)

    success_count = 0
    error_count = 0
    skipped_count = 0

    for idx, row in enumerate(unique_rows, 1):
        test_name = clean_value(row.get("Test Name") or row.get("Test") or row.get("name") or row.get("Name"))

        if test_name in existing_names:
            skipped_count += 1
            print(f"[{idx}/{total_tests}] [SKIP] '{test_name}' already exists.", flush=True)
            continue

        # الأعمدة دي اختيارية — لو موجودة هيستخدمها، لو مش موجودة هيمشي بقيم افتراضية
        sample_type = clean_value(row.get("Sample") or row.get("sample_type"))
        price = clean_price(row.get("Price") or row.get("price"))
        prep_en = clean_value(row.get("Preparation (English)"))
        prep_ar = clean_value(row.get("التحضير المطلوب (عربي)"))
        excel_duration = clean_value(row.get("Duration") or row.get("duration") or row.get("المدة"))

        instructions_parts = []
        if prep_ar:
            instructions_parts.append(prep_ar)
        if prep_en:
            instructions_parts.append(f"({prep_en})")
        # من غير default هنا — لو الإكسل فاضي، هنسيب المجال لجيميناي يولّد بدل
        # ما نقفل الاختيار بقيمة ثابتة من الأول.
        excel_instructions = "\n".join(instructions_parts) if instructions_parts else ""

        req = KnowledgeGenerationRequest(
            name=test_name,
            patient_instructions=excel_instructions or None,
            duration=excel_duration or None,
            price=price,
            entity_type=EntityType.LAB,
        )

        print(f"[{idx}/{total_tests}] Generating knowledge for: '{test_name}'...", flush=True)
        gen = generate_knowledge_with_backoff(req)

        if not gen:
            error_count += 1
            print(f"[{idx}/{total_tests}] [ERROR] Skipping '{test_name}' due to repeated LLM error.", flush=True)
            continue

        description = get_field(gen, "description", default=test_name)
        aliases = get_field(gen, "aliases", "alias_names", default=[test_name])
        keywords = get_field(gen, "keywords", default=[test_name])
        gen_sample_type = get_field(gen, "sample_type", default="")
        gen_duration = get_field(gen, "duration", default="")
        gen_instructions = get_field(gen, "patient_instructions", default="")

        # الأولوية دايماً لأي قيمة موجودة في الإكسل، وإلا اللي جيميناي ولّده،
        # وإلا فولباك أخير ثابت (بس بيتستخدم فعلياً بس لو الاتنين فشلوا).
        final_sample_type = sample_type or gen_sample_type or None
        final_duration = excel_duration or gen_duration or FALLBACK_DURATION
        final_instructions = excel_instructions or gen_instructions or FALLBACK_INSTRUCTIONS

        # alias_names دلوقتي flat list من الأساس (بعد تصحيح الـ schema)،
        # بس بنسيب فحص بسيط احتياطي لأي شكل غير متوقع.
        if isinstance(aliases, list):
            alias_list = aliases
        elif hasattr(aliases, "aliases"):
            alias_list = list(aliases.aliases)
        else:
            alias_list = [str(aliases)]

        keyword_list = keywords if isinstance(keywords, list) else [str(keywords)]

        # بناء search_text بنفس منطق embedding_simple بدل ما ناخده من gen مباشرة
        search_text = build_search_text(
            name=test_name,
            description=description,
            keywords=keyword_list,
            aliases=alias_list,
        )

        if args.dry_run:
            # ولا حفظ في الداتابيز ولا embedding/FAISS — بس عرض اللي كان هيتحفظ
            success_count += 1
            print(f"[{idx}/{total_tests}] [DRY-RUN OK] '{test_name}'", flush=True)
            print(f"   sample_type          : {final_sample_type}", flush=True)
            print(f"   duration             : {final_duration}", flush=True)
            print(f"   patient_instructions : {final_instructions}", flush=True)
            print(f"   alias_names          : {alias_list}", flush=True)
            print(f"   keywords             : {keyword_list}", flush=True)
            print(f"   description          : {str(description)[:120]}...", flush=True)
        else:
            with app.app_context():
                lab_entity = LabService(
                    laboratory_id=lab_org_id,
                    name=test_name,
                    price=price,
                    sample_type=final_sample_type,
                    durations=final_duration,
                    patient_instructions=final_instructions,
                    description=description,
                    alias_names=alias_list,   # عمود JSON — بيتخزن كـ list مباشرة
                    keywords=keyword_list,    # عمود JSON — بيتخزن كـ list مباشرة
                    search_text=search_text,
                )
                db.session.add(lab_entity)
                db.session.commit()
                assigned_id = lab_entity.id

                try:
                    embedding = generate_embedding(search_text)
                    upsert_vector(lab_id=assigned_id, name=test_name, embedding=embedding)
                except Exception as vec_err:
                    print(f"   ⚠️ Vector upsert failed for '{test_name}': {vec_err}", flush=True)

            success_count += 1
            print(f"[{idx}/{total_tests}] [SUCCESS ID={assigned_id}] '{test_name}' -> {str(description)[:65]}...", flush=True)

        time.sleep(0.8)  # basic rate-limit pacing

    print("\n==========================================", flush=True)
    print("=== ADD NEW TESTS COMPLETE ===", flush=True)
    print(f" Total in file:           {total_tests}", flush=True)
    print(f" Successfully Added:      {success_count}", flush=True)
    print(f" Skipped (already exist): {skipped_count}", flush=True)
    print(f" Errors:                  {error_count}", flush=True)
    print("==========================================", flush=True)


if __name__ == "__main__":
    main()