"""
software_services/lab_service_services.py
"""

from models.models import LabService, db
from software_service.laboratory_services import LaboratoryService
from software_service.base_service import BaseService



class LabServiceService(BaseService):

    # -- list / search --------------------------------------------------------

    @staticmethod
    def get_all_labs(page=1, per_page=10, search=None):
        query = LabService.query

        if search:
            query = query.filter(
                db.or_(
                    LabService.name.ilike(f'%{search}%'),
                    LabService.sample_type.ilike(f'%{search}%'),
                )
            )

        query = query.order_by(LabService.name.asc())
        return BaseService.paginate(query, page=page, per_page=per_page, success_msg="تم العثور على التحاليل")

    # -- single -----------------------------------------------------------------

    @staticmethod
    def get_lab_by_id(lab_id):
        lab = db.session.get(LabService, lab_id)
        if not lab:
            return None, "التحليل غير موجود"
        return lab, "تم العثور على التحليل"

    # -- create -------------------------------------------------------------------

   # software_services/lab_service_services.py
# Replace ONLY the create_lab method with this one.

    @staticmethod
    def create_lab(name, price, laboratory_id=None, sample_type=None,
                    durations=None, patient_instructions=None,
                    description=None, alias_names=None, keywords=None,
                    search_text=None):
        if not name or not name.strip():
            return None, "اسم التحليل مطلوب"
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, "السعر غير صحيح"

        clean_name = name.strip()
        existing = LabService.query.filter(LabService.name.ilike(clean_name)).first()
        if existing:
            return existing, "التحليل موجود بالفعل"

        if laboratory_id is None:
            try:
                laboratory_id = LaboratoryService.get_current_laboratory_id()
            except ValueError as e:
                return None, str(e)

        lab = LabService(
            laboratory_id=laboratory_id,
            name=clean_name,
            price=price,
            sample_type=(sample_type or "").strip() or None,
            durations=(durations or "").strip() or None,
            patient_instructions=(patient_instructions or "").strip() or None,
            # knowledge fields (all optional, JSON columns take real lists)
            description=(description or "").strip() or None,
            alias_names=list(alias_names) if alias_names else None,
            keywords=list(keywords) if keywords else None,
            search_text=(search_text or "").strip() or None,
        )
        return BaseService.commit(lab, success_msg="تم إنشاء التحليل بنجاح", error_prefix="حدث خطأ أثناء إنشاء التحليل")
    # -- update -------------------------------------------------------------------

    

    @staticmethod
    def update_lab(lab_id, name=None, price=None, sample_type=None,
                    durations=None, patient_instructions=None,
                    description=None, alias_names=None, keywords=None,
                    search_text=None):
        lab = db.session.get(LabService, lab_id)
        if not lab:
            return None, "التحليل غير موجود"

        # ---- validate everything first, mutate after ----
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                return None, "السعر غير صحيح"

        clean_name = None
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                return None, "اسم التحليل مطلوب"
            duplicate = LabService.query.filter(
                db.func.lower(LabService.name) == clean_name.lower(),
                LabService.id != lab_id,
            ).first()
            if duplicate:
                return None, "يوجد تحليل آخر بنفس الاسم"

        # ---- apply ----
        if clean_name is not None:
            lab.name = clean_name
        if price is not None:
            lab.price = price
        if sample_type is not None:
            lab.sample_type = sample_type.strip() or None
        if durations is not None:
            lab.durations = durations.strip() or None
        if patient_instructions is not None:
            lab.patient_instructions = patient_instructions.strip() or None

        # knowledge fields (JSON columns take real lists)
        if description is not None:
            lab.description = description.strip() or None
        if alias_names is not None:
            lab.alias_names = list(alias_names) or None
        if keywords is not None:
            lab.keywords = list(keywords) or None
        if search_text is not None:
            lab.search_text = search_text.strip() or None

        return BaseService.update_commit(lab, success_msg="تم تحديث التحليل بنجاح", error_prefix="حدث خطأ أثناء التحديث")
    # -- delete -------------------------------------------------------------------

    @staticmethod
    def delete_lab(lab_id):
        lab = db.session.get(LabService, lab_id)
        if not lab:
            return None, "التحليل غير موجود"

        deleted_lab, msg = BaseService.delete(
            lab, success_msg="تم حذف التحليل بنجاح", error_prefix="حدث خطأ أثناء الحذف"
        )

        # لو الحذف من الداتابيز نجح، لازم نشيل الـ vector بتاعه من FAISS
        # كمان، وإلا هيفضل يتيم فيه ويطلع في نتائج semantic search لتحليل
        # اتمسح فعلياً. فشل مسح الـ vector ملوش داعي يفشّل عملية الحذف
        # نفسها -- بس بنسجله عشان نلاحظه لو حصل.
        if deleted_lab is not None:
            try:
                from knowledge.vector_store import delete_vector
                delete_vector(lab_id)
            except Exception:
                import traceback
                print(f"=== VECTOR STORE DELETE FAILED for lab_id={lab_id} ===")
                traceback.print_exc()

        return deleted_lab, msg

    # -- used elsewhere (e.g. inquiry review dropdown) -----------------------------

    @staticmethod
    def get_all_labs_flat():
        """Unpaginated list - used where a full dropdown of labs is needed."""
        return LabService.query.order_by(LabService.name.asc()).all(), "تم العثور على التحاليل"