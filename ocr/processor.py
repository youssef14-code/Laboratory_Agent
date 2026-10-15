import logging
import os
import uuid
from typing import Optional, Tuple

from ocr.classifier import analyze_prescription_image
from software_service.client_services import ClientService
from software_service.inquiry_services import InquiryService
from software_service.subscripition_service import SubscriptionService
from models.models import Status, db
from notified_center.EmailSender import send_production_alert, send_pending_prescription_email

try:
    from utils.trace_logger import trace_logger
except ImportError:
    class DummyTraceLogger:
        def step(self, *args, **kwargs): pass
        def log_db_operation(self, *args, **kwargs): pass
        def log_llm_call(self, *args, **kwargs): pass
        def log_output(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
    trace_logger = DummyTraceLogger()

logger = logging.getLogger(__name__)

# ── Image validity check (magic bytes) ──────────────────────────────────────
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),        # JPEG
    (b"\x89PNG\r\n\x1a\n", "png"),   # PNG
    (b"GIF87a", "gif"),              # GIF
    (b"GIF89a", "gif"),              # GIF
)


def _detect_image_extension(image_bytes: bytes) -> Optional[str]:
    """Return the correct file extension based on magic bytes, or None if unrecognized."""
    for signature, extension in _IMAGE_SIGNATURES:
        if image_bytes.startswith(signature):
            return extension
    if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 16 and b"WEBP" in image_bytes[8:16]:
        return "webp"
    return None


def _looks_like_valid_image(image_bytes: bytes) -> bool:
    """Verifies image bytes match a known image magic byte signature."""
    if not image_bytes or len(image_bytes) < 16:
        return False
    return _detect_image_extension(image_bytes) is not None


def _save_prescription_image(image_bytes: bytes, sender_id: str) -> Tuple[str, str]:
    """Writes image bytes to disk with their real extension and returns (filename, absolute_path)."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uploads_dir = os.path.join(project_dir, "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    extension = _detect_image_extension(image_bytes) or "jpg"
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(uploads_dir, filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    logger.info(
        "[PRESCRIPTION INTAKE] Saved Image: %s | sender_id=%s",
        image_path, sender_id,
    )
    trace_logger.step(
        "Prescription Image Ingested",
        input_data={
            "sender_id": sender_id,
            "image_path": image_path,
            "bytes_len": len(image_bytes),
        },
    )
    return filename, image_path


def _determine_prescription_pending(ocr_result) -> bool:
    """Returns True if prescription requires manual doctor review due to low confidence."""
    if not ocr_result.tests:
        return True
    return any(test.confidence < 0.90 for test in ocr_result.tests)


def _save_inquiry_record(phone_number: str, comes_from: str, filename: str, ocr_result, pending: bool, laboratory_id: int = 1) -> Tuple[float, Optional[int]]:
    """Persists prescription inquiry in DB and returns (min_confidence, inquiry_id)."""
    min_confidence = min((t.confidence for t in ocr_result.tests), default=0.0)
    services_mentioned = ", ".join(t.name for t in ocr_result.tests) if ocr_result.tests else None
    inquiry_status = Status.PENDING if pending else Status.CONFIRMED

    # 👈 تم تغيير create_inquiry إلى save_inquiry
    inquiry, msg = InquiryService.save_inquiry(
        laboratory_id=laboratory_id,
        phone_number=phone_number,
        comes_from=comes_from,
        prescription_img=filename,
        ocr_extracted_text=ocr_result.extracted_text,
        confidence_score=min_confidence,
        services_mentioned=services_mentioned,
        status=inquiry_status,
    )

    inquiry_id = inquiry.id if inquiry else None
    logger.info(
        "[PRESCRIPTION INQUIRY SAVED] Inquiry ID: %s | Status: %s",
        inquiry_id,
        inquiry_status.value,
    )
    trace_logger.log_db_operation(
        "save_inquiry",
        "inquiries",
        success=True,
        extra={"status": inquiry_status.value, "min_confidence": min_confidence},
    )
    return min_confidence, inquiry_id


def process_prescription_ocr(
    image_path: str,
    phone_number: str,
    comes_from: str,
    laboratory_id: int = 1,
) -> dict:
    """
    Main entry-point called by service/message_processor.py for OCR pipeline.
    """
    try:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        ocr_result, ocr_usage = analyze_prescription_image(image_path)
        filename = os.path.basename(image_path)

        # 1. حالة الصور غير الصالحة / سبام
        if not ocr_result.is_prescription:
            return {
                "success": False,
                "classified_as": "spam",
                "confidence": 0,
                "extracted_text": "",
                "services_mentioned": [],
                "inquiry_id": None,
                "ocr_usage": ocr_usage,
                "message": "الصورة ليست روشتة طبية صالحة.",
            }

        # 2. تحديد هل تحتاج مراجعة طبيب (Pending) أم واضحة جداً (Success)
        pending = _determine_prescription_pending(ocr_result)
        min_confidence, inquiry_id = _save_inquiry_record(
            phone_number=phone_number,
            comes_from=comes_from,
            filename=filename,
            ocr_result=ocr_result,
            pending=pending,
            laboratory_id=laboratory_id,
        )

        test_names = [t.name for t in ocr_result.tests if t.name]

        # 3. روشتة خطها غير واضح -> تحويل للطبيب
        if pending:
            if inquiry_id:
                try:
                    send_pending_prescription_email(
                        inquiry_id=inquiry_id,
                        comes_from=comes_from,
                        confidence_score=min_confidence,
                        extracted_tests=", ".join(test_names) or "لم يتم استخراج تحاليل",
                        ocr_extracted_text=ocr_result.extracted_text or "",
                    )
                except Exception as mail_err:
                    logger.error("[PRESCRIPTION] Pending email failed: %s", mail_err)
            return {
                "success": False,
                "classified_as": "prescription",
                "confidence": int(min_confidence * 100),
                "extracted_text": ocr_result.extracted_text,
                "services_mentioned": test_names,
                "inquiry_id": inquiry_id,
                "ocr_usage": ocr_usage,
                "message": "الروشتة قيد مراجعة الطبيب المختص.",
            }

        # 4. روشتة واضحة ومقروءة بنجاح (All tests >= 0.80) -> جاهزة للرد الآلي
        return {
            "success": True,
            "classified_as": "prescription",
            "confidence": int(min_confidence * 100),
            "extracted_text": ocr_result.extracted_text,
            "services_mentioned": test_names,
            "inquiry_id": inquiry_id,
            "ocr_usage": ocr_usage,
            "message": "تمت قراءة الروشتة واستخراج التحاليل بنجاح.",
        }

    except Exception as e:
        logger.exception("[process_prescription_ocr] Error: %s", e)
        send_production_alert(
            subject="Prescription OCR Error in Processor",
            body_or_error=e,
            context={"image_path": image_path, "phone": phone_number},
        )
        return {
            "success": False,
            "classified_as": "system_error",
            "confidence": 0,
            "extracted_text": "",
            "services_mentioned": [],
            "inquiry_id": None,
            "ocr_usage": None,
            "message": f"حدث خطأ أثناء معالجة الصورة: {e}",
        }