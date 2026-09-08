"""
New flow  (1 API call):
    analyze_prescription()  ->  route based on process_success flag

Routing:
    is_error = True  (technical/system failure: no API key, unreadable
                       image, Gemini call raised, bad JSON, etc.)
        -> do NOT save Inquiry
        -> return success=False, classified_as="system_error"

    is_spam = True  OR  is_prescription = False
        -> do NOT save Inquiry
        -> return success=False, classified_as="spam"

    process_success = True  (overall_confidence >= CONFIDENCE_THRESHOLD, i.e. 90)
        -> save Inquiry as REVIEWED
        -> return success=True  -> LangGraph agent replies automatically

    process_success = False (overall_confidence < CONFIDENCE_THRESHOLD)  AND  is_prescription = True
        -> save Inquiry as PENDING for manual doctor review
        -> return success=False -> static "waiting for doctor" reply
"""

import os
import logging
from ocr.classifier import analyze_prescription, CONFIDENCE_THRESHOLD
from software_service.inquiry_services import InquiryService

logger = logging.getLogger(__name__)

# NOTE: CONFIDENCE_THRESHOLD is imported from ocr/classifier.py rather than
# redefined here. classifier.py is the source of truth that actually
# computes process_success against this value; keeping a second local
# constant risked the two silently drifting apart.


def process_prescription_ocr(
    image_path: str,
    phone_number: str,
    comes_from: str,
    laboratory_id: int = 1,
) -> dict:
    """
    Main entry-point called by service/message_processor.py.

    Args:
        image_path:     Absolute path to the downloaded prescription image.
        phone_number:   Sender's phone number (may be empty for FB users).
        comes_from:     Origin string, e.g. "Facebook:<sender_id>:<page_id>".
        laboratory_id:  ID of the laboratory record (default: 1).

    Returns:
        dict with keys:
            success         bool
            classified_as   "prescription" | "spam" | "system_error"
            confidence      int   (0-100)
            extracted_text  str
            services_mentioned list[str]
            inquiry_id      int | None
            message         str
    """
    logger.info(
        "[OCR Processor] start | image=%s | phone=%s | comes_from=%s | lab_id=%s",
        os.path.basename(image_path), phone_number, comes_from, laboratory_id,
    )

    # -- Single Gemini call --------------------------------------------------
    ocr = analyze_prescription(image_path)

    is_prescription     = ocr.get("is_prescription", False)
    is_spam             = ocr.get("is_spam", True)
    is_error            = ocr.get("is_error", False)
    overall_confidence  = ocr.get("overall_confidence", 0)
    process_success     = ocr.get("process_success", False)
    labs                = ocr.get("labs", [])
    unknown_items       = ocr.get("unknown_items", [])
    notes               = ocr.get("notes", "")

    logger.info(
        "[OCR Processor] classification result | is_prescription=%s | is_spam=%s | "
        "is_error=%s | confidence=%s | process_success=%s | labs=%d | unknown_items=%d",
        is_prescription, is_spam, is_error, overall_confidence, process_success,
        len(labs), len(unknown_items),
    )

    # -- Technical/system failure (NOT a spam judgement) -----------------------
    # Distinguished from "spam" so transient failures (Gemini outage, bad
    # image, malformed JSON) don't get silently discarded as if the model
    # had actually looked at the document and rejected it.
    if is_error:
        logger.error(
            "[OCR Processor] technical error during OCR, not a classification | notes=%s",
            notes,
        )
        return {
            "success":            False,
            "classified_as":      "system_error",
            "confidence":         overall_confidence,
            "extracted_text":     "",
            "services_mentioned": [],
            "inquiry_id":         None,
            "message":            f"OCR processing failed due to a system error. {notes}",
        }

    # -- Spam / non-prescription ----------------------------------------------
    # Checks both flags: is_spam is the model's explicit judgement, while
    # not is_prescription is a fallback for cases where the model set
    # is_prescription=False but left is_spam unset/inconsistent.
    if is_spam or not is_prescription:
        logger.warning(
            "[OCR Processor] rejected as spam/non-prescription | is_spam=%s | "
            "is_prescription=%s | notes=%s",
            is_spam, is_prescription, notes,
        )
        return {
            "success":            False,
            "classified_as":      "spam",
            "confidence":         overall_confidence,
            "extracted_text":     "",
            "services_mentioned": [],
            "inquiry_id":         None,
            "message":            f"Document rejected - not a prescription. {notes}",
        }

    # -- Build extracted text from labs ----------------------------------------
    lab_lines = []
    for lab in labs:
        # Defensive: lab is expected to be a dict per the schema, but Gemini's
        # JSON output isn't strictly schema-enforced here, so guard anyway.
        if isinstance(lab, dict):
            line = lab.get("standardized_name") or lab.get("matched_text", "")
        else:
            logger.warning(
                "[OCR Processor] lab item not a dict (got %s) | value=%r",
                type(lab).__name__, lab,
            )
            line = str(lab)
        if line:
            lab_lines.append(line)

    # Same defensive handling for unknown_items - this is what was crashing:
    # Gemini sometimes returns [{"text": "...", ...}] instead of ["..."],
    # and str.join() only accepts strings, not dicts.
    if unknown_items:
        unknown_strs = []
        for item in unknown_items:
            if isinstance(item, dict):
                unknown_strs.append(item.get("text") or item.get("matched_text") or str(item))
            else:
                unknown_strs.append(str(item))
        logger.info(
            "[OCR Processor] unreadable items found | count=%d | items=%s",
            len(unknown_strs), unknown_strs,
        )
        lab_lines.append("Unreadable items: " + ", ".join(unknown_strs))

    extracted_text  = "\n".join(lab_lines)
    services_str    = ", ".join(
        (lab.get("standardized_name") or lab.get("matched_text", "")) if isinstance(lab, dict) else str(lab)
        for lab in labs
        if (isinstance(lab, dict) and (lab.get("standardized_name") or lab.get("matched_text")))
        or (not isinstance(lab, dict) and lab)
    ) or None
    filename = os.path.basename(image_path)

    # -- High confidence -> automated flow -------------------------------------
    if process_success:
        from models.models import Status

        logger.info(
            "[OCR Processor] high confidence -> saving as REVIEWED | services=%s",
            services_str,
        )

        # NOTE: InquiryService.save_inquiry() (like the other InquiryService
        # methods, e.g. get_inquiry_by_id) returns a plain
        # (object_or_None, message) tuple, NOT an object with .success /
        # .inquiry attributes. Unpack it directly instead of poking at
        # attributes that don't exist -- that mismatch was causing
        # "'tuple' object has no attribute 'success'" even on successful
        # saves.
        try:
            saved_inquiry, save_message = InquiryService.save_inquiry(
                laboratory_id=laboratory_id,
                phone_number=phone_number,
                comes_from=comes_from,
                prescription_img=filename,
                ocr_extracted_text=extracted_text,
                confidence_score=overall_confidence / 100.0,
                services_mentioned=services_str,
                status=Status.DONE,
            )
        except Exception as exc:
            logger.exception("❌ [OCR Processor] save_inquiry failed (REVIEWED): %s", exc)
            from notified_center import send_production_alert
            send_production_alert(
                subject="OCR Processor Save Inquiry Failure (REVIEWED)",
                body_or_error=exc,
                context={"image": filename, "phone": phone_number, "comes_from": comes_from},
            )
            saved_inquiry, save_message = None, "Exception occurred"

        if not saved_inquiry:
            logger.error(
                "[OCR Processor] InquiryService reported failure | message=%s",
                save_message,
            )
        else:
            logger.info(
                "[OCR Processor] inquiry saved | inquiry_id=%s",
                saved_inquiry.id,
            )

        return {
            "success":            True,
            "classified_as":      "prescription",
            "confidence":         overall_confidence,
            "extracted_text":     extracted_text,
            "services_mentioned": [
                (lab.get("standardized_name") or lab.get("matched_text", "")) if isinstance(lab, dict) else str(lab)
                for lab in labs
            ],
            "inquiry_id": saved_inquiry.id if saved_inquiry else None,
            "ocr_usage": ocr.get("ocr_usage"),
            "message": (
                f"Prescription parsed successfully "
                f"(confidence={overall_confidence}%)."
            ),
        }

    # -- Low confidence -> manual doctor review ---------------------------------
    logger.info(
        "[OCR Processor] low confidence (%s%% < %s%%) -> saving for manual review",
        overall_confidence, CONFIDENCE_THRESHOLD,
    )

    try:
        saved_inquiry, save_message = InquiryService.save_inquiry(
            laboratory_id=laboratory_id,
            phone_number=phone_number,
            comes_from=comes_from,
            prescription_img=filename,
            ocr_extracted_text=(
                "[Low Confidence - Waiting for Manual Review]\n" + extracted_text
            ),
            confidence_score=overall_confidence / 100.0,
            services_mentioned=None,
        )
    except Exception as exc:
        logger.exception("❌ [OCR Processor] save_inquiry failed (manual review): %s", exc)
        from notified_center import send_production_alert
        send_production_alert(
            subject="OCR Processor Save Inquiry Failure (Manual Review)",
            body_or_error=exc,
            context={"image": filename, "phone": phone_number, "comes_from": comes_from},
        )
        saved_inquiry, save_message = None, "Exception occurred"

    if not saved_inquiry:
        logger.error(
            "[OCR Processor] InquiryService reported failure (manual review) | message=%s",
            save_message,
        )
    else:
        logger.info(
            "[OCR Processor] inquiry saved for manual review | inquiry_id=%s",
            saved_inquiry.id,
        )

    return {
        "success":            False,
        "classified_as":      "prescription",
        "confidence":         overall_confidence,
        "extracted_text":     extracted_text,
        "services_mentioned": [],
        "inquiry_id": saved_inquiry.id if saved_inquiry else None,
        "ocr_usage": ocr.get("ocr_usage"),
        "message": (
            f"Prescription saved for manual review "
            f"(confidence={overall_confidence}% < threshold {CONFIDENCE_THRESHOLD}%)."
        ),
    }