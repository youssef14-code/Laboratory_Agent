from models.models import Laboratory, Page

from query_refiner import refine_query
from search.search_manager import run_search
from rag.context_builder import build_context


class LabDataService:

    @staticmethod
    def get_laboratory_object(page_id):
        try:
            return Laboratory.query.join(Page).filter(Page.page_id == page_id).first()
        except Exception as e:
            print(f"[LabDataService] DB error in get_laboratory_object: {e}")
            return None

    @staticmethod
    def _build_lab_info(lab) -> str:
        branches_info = "\n".join(
            f"- Branch Address: {b.address}"
            + (f" | Phone: {b.phone}" if b.phone else "")
            + (f" | Working Hours: {b.working_hours}" if b.working_hours else "")
            for b in lab.branches
        ) or "No branches registered."

        return (
            f"Laboratory Name: {lab.name}\n"
            f"Info: {lab.info}\n"
            f"Branches:\n{branches_info}"
        )

    @staticmethod
    def get_lab_info(page_id) -> str:
        """معلومات عامة عن المعمل (الاسم، الفروع) — مش مرتبطة بسؤال المستخدم، فمفيش داعي لفلترتها."""
        lab = LabDataService.get_laboratory_object(page_id)
        if lab:
            return LabDataService._build_lab_info(lab)
        return "No laboratory found for the given page ID."

    @staticmethod
    def get_relevant_services_info(page_id, user_query: str, top_k: int = 5) -> str:
        """
        بديل get_services_info القديمة — بدل ما ترجّع كل التحاليل، بتعدّي
        على الـ RAG pipeline (refine -> search -> context) وترجع بس
        التحاليل ذات الصلة بسؤال المستخدم الفعلي.
        """
        lab = LabDataService.get_laboratory_object(page_id)
        if not lab:
            return "No laboratory found for the given page ID."

        if not user_query or not user_query.strip():
            return "No specific query provided — cannot retrieve relevant services."

        refined_queries = refine_query(user_query)

        search_output = run_search(refined_queries)
        results = search_output["results"]

        if not results[:top_k]:
            return "No matching lab services found for this query."

        context = build_context(results[:top_k])
        return context