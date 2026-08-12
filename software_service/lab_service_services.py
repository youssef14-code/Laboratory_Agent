"""
software_services/lab_service_services.py
"""

from models.models import LabService, db
from software_service.laboratory_services import LaboratoryService
from software_service.base_service import BaseService



class LabServiceService:

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

    @staticmethod
    def create_lab(name, price, laboratory_id=None, sample_type=None,
                    durations=None, patient_instructions=None):
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
            name=name.strip(),
            price=price,
            sample_type=(sample_type or "").strip() or None,
            durations=(durations or "").strip() or None,
            patient_instructions=(patient_instructions or "").strip() or None,
        )
        return BaseService.commit(lab, success_msg="تم إنشاء التحليل بنجاح", error_prefix="حدث خطأ أثناء إنشاء التحليل")

    # -- update -------------------------------------------------------------------

    @staticmethod
    def update_lab(lab_id, name=None, price=None, sample_type=None,
                    durations=None, patient_instructions=None):
        lab = db.session.get(LabService, lab_id)
        if not lab:
            return None, "التحليل غير موجود"

        if name is not None:
            lab.name = name.strip()
        if price is not None:
            try:
                lab.price = float(price)
            except (TypeError, ValueError):
                return None, "السعر غير صحيح"
        if sample_type is not None:
            lab.sample_type = sample_type.strip() or None
        if durations is not None:
            lab.durations = durations.strip() or None
        if patient_instructions is not None:
            lab.patient_instructions = patient_instructions.strip() or None

        return BaseService.update_commit(lab, success_msg="تم تحديث التحليل بنجاح", error_prefix="حدث خطأ أثناء التحديث")

    # -- delete -------------------------------------------------------------------

    @staticmethod
    def delete_lab(lab_id):
        lab = db.session.get(LabService, lab_id)
        if not lab:
            return None, "التحليل غير موجود"
        return BaseService.delete(lab, success_msg="تم حذف التحليل بنجاح", error_prefix="حدث خطأ أثناء الحذف")

    # -- used elsewhere (e.g. inquiry review dropdown) -----------------------------

    @staticmethod
    def get_all_labs_flat():
        """Unpaginated list - used where a full dropdown of labs is needed."""
        return LabService.query.order_by(LabService.name.asc()).all(), "تم العثور على التحاليل"