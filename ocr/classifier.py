"""
ocr/classifier.py

Single-call Gemini multimodal OCR engine.
Replaces the old two-step flow (classify → extract) with ONE API call
that classifies the document AND extracts lab tests simultaneously.

Returned dict shape:
{
    "document_type":       str,   # e.g. "lab_prescription", "advertisement", ...
    "is_prescription":     bool,
    "is_spam":             bool,
    "is_error":            bool,  # True only for technical/system failures
                                   # (missing API key, unreadable image, API
                                   # call exception, JSON parse error). This
                                   # is DIFFERENT from is_spam: is_spam means
                                   # "the model looked at a real document and
                                   # decided it isn't a prescription", while
                                   # is_error means "we never got a reliable
                                   # judgement at all".
    "overall_confidence":  int,   # 0-100
    "process_success":     bool,  # True if overall_confidence >= CONFIDENCE_THRESHOLD
    "labs": [
        {
            "standardized_name": str,
            "matched_text":      str,
            "confidence":        int,  # 0-100
            "source":            str,  # "checkbox" | "written_text"
        },
        ...
    ],
    "unknown_items": [str, ...],
    "notes":               str
}
"""

import os
import json
import time
import logging

from PIL import Image
from google import genai
from google.genai import types


logger = logging.getLogger(__name__)


# Single source of truth for the confidence threshold. Import this from
# service.py instead of redefining it there — two copies of the same
# constant is how they drift out of sync.
CONFIDENCE_THRESHOLD = 90

# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT = """
You are an expert laboratory prescription OCR system specialized in reading printed and handwritten medical prescriptions from images.

Your task is to analyze the uploaded prescription image with high medical precision and return the results STRICTLY as a JSON object.

====================
STEP 0: MANDATORY FULL-PAGE SCAN (DO THIS FIRST, SILENTLY)
====================
Before extracting anything, you must scan the ENTIRE image region by region, not just the center or the most visually obvious area:
1. Top-left, top-right, center, bottom-left, bottom-right, and any margins/edges of the page.
2. If the prescription form has multiple columns or sections of checkboxes (e.g. "Hematology", "Biochemistry", "Hormones", "Serology"), you must scan EVERY section — do not stop after the first section you notice.
3. If the image resolution makes any region too small/blurry to read confidently, mentally note that region as LOW_VISIBILITY. Any checkbox inside a LOW_VISIBILITY region can NEVER be marked as CLEAR_MARK (see Step 2) — it must go to "unknown_items" or be skipped if unmarked/unreadable.
4. Do not assume symmetry or patterns (e.g. do not assume "if the first 3 boxes in a column are checked, similar boxes elsewhere are checked too"). Every single box is judged independently and only on its own visible mark.
5. Do not stop scanning early just because you already found some checked items — a real prescription can have checked items scattered across the entire page, including areas far from each other.
6. A single prescription may contain BOTH a checkbox panel AND separately handwritten/typed test names outside that panel. Scan for both kinds independently — do not assume the whole page is one type or the other.


====================
STEP 1: COUNT TOTAL TESTS (CRITICAL)
====================
Before extracting the details of each test, you MUST count the TOTAL number of tests requested in the image.
- Count every clear marked checkbox.
- Count every handwritten or typed test name.
- Include unreadable or ambiguous tests in your count.
- Output this total exact number as "total_tests_detected".


====================
EXTRACTION RULES & ANTI-HALLUCINATION (STRICT — CRITICAL)
====================
- Extract ONLY laboratory tests/investigations that are LITERALLY WRITTEN or MARKED in the image.
- Do NOT add related/commonly-ordered tests. Every extracted test must have visible evidence.
- Ambiguous abbreviations -> put them in "unknown_items".
- Recognize common shorthand ONLY when it maps to exactly ONE test (e.g., "S. Ca" -> Serum Calcium, "Vit D" -> Vitamin D, "CBC" -> Complete Blood Count).
- IGNORE doctor's notes, medications, radiology/imaging requests (X-Ray, CT, MRI, Ultrasound), or any non-lab-test text — even if visible in the image. Do not include radiology in "labs" or "unknown_items".
- Never expand a single abbreviation or panel name into multiple separate standardized tests unless each component is individually written or checked.
- Every test you extract, from ANY source, must be tagged with "source" as
  either "checkbox" or "written_text" (see STEP 2 and STEP 3 below). This
  tag determines how its confidence is calculated later — get it right.

====================
STEP 2: CHECKBOX / SELECTION-MARK VERIFICATION (CRITICAL, DO PER-ITEM)
====================
For EVERY checkbox/circle candidate found during your Step 0 scan, classify what is inside/around the box using exactly one of these states:

- "EMPTY" -> nothing inside, no mark touching the box.
- "CLEAR_MARK" -> unambiguous tick/X/fill/circle fully enclosing or clearly crossing the box, OR a deliberate pen stroke striking through or underlining the printed test name itself (even if the box is empty).
- "AMBIGUOUS" -> faint, partial, smudged, cut-off, or unclear mark.
- "LOW_VISIBILITY" -> the region is too blurry/small/low-resolution to judge reliably, regardless of whether a mark seems present.

Rules:
- ONLY items with state = CLEAR_MARK are eligible for the "labs" array.
- Items where BOTH the box is empty AND the printed text has no pen marks over/under it are considered unselected. They must NEVER appear in "labs" or "unknown_items" — do not mention them at all.
- Items with state = AMBIGUOUS or LOW_VISIBILITY go to "unknown_items" (never guess them into "labs").
- Default bias: if you are not fully certain a mark is CLEAR_MARK, downgrade it to AMBIGUOUS, never upgrade an unclear mark to CLEAR_MARK.
- The presence of a printed test name next to a box is NEVER evidence of selection by itself. Only the mark itself is evidence.
- Do not infer a checkbox is marked based on nearby handwriting, doctor's signature, stamps, or unrelated ink marks — the mark must be directly on/inside/around that specific box or its printed text.
- CONFIDENCE FOR CHECKBOX ITEMS IS FIXED AT 40. Unlike written text (STEP 3), there is no legibility judgement to make here — a checkbox is either CLEAR_MARK (confidence = 40, goes to "labs") or it isn't (goes to "unknown_items" or is skipped entirely). Never output a checkbox-sourced lab with a confidence other than 40 — not 50, not 90, not 100, regardless of how dark, bold, or unmistakable the mark looked.
- LONG/ANGLED STROKES: a tick mark is often drawn as a long diagonal stroke that starts well outside the box and only enters/crosses the box near its end (a "tail"). Judge these the same as any other tick: if the stroke clearly crosses or touches THAT box, it's CLEAR_MARK for that box — the tail extending outside the box doesn't disqualify it. But judge each box independently: if a neighboring box merely sits close to where the tail happens to pass nearby without the stroke actually crossing into it, that neighboring box stays EMPTY. Do not mark a box just because a stroke aimed at a different box runs near it.

For a checked item, "matched_text" must literally describe the visual mark you saw, e.g. "clear X mark inside box next to printed 'CBC'", "circle drawn around printed 'Vit D'", or "pen line drawn through the printed text 'TSH'". If you cannot describe a specific visual mark, do not include the item.

Every item added to "labs" through this checkbox process MUST be tagged
"source": "checkbox" with "confidence": 40.

====================
STEP 3: WRITTEN-TEXT TEST EXTRACTION & CONFIDENCE (NO CHECKBOX INVOLVED)
====================
Some prescriptions (or parts of a prescription) have NO checkbox/circle
at all — the doctor simply wrote the test name directly (handwritten or
typed), with no box or mark to verify. This is a DIFFERENT extraction
path from STEP 2 and does not use CLEAR_MARK/AMBIGUOUS/etc.

For each such test:
- Extract it if the written test name is legible and identifiable
  (directly, via common shorthand resolution, or via careful reading of
  imperfect handwriting per your genuine best effort — same spirit as
  resolving OCR noise, just for handwriting clarity here).
- Tag it "source": "written_text".
- Set its "confidence" based on GENUINE handwriting/text legibility —
  this is a real judgment call, unlike the checkbox confidence in STEP 2,
  which is always fixed at 40:
  - Clearly legible, unambiguous text -> 90-100.
  - Mostly legible but with minor uncertainty (e.g. one questionable
    letter, slightly smudged) -> 65-89.
  - Hard to read but you made a confident best-effort identification ->
    40-64.
  - If you cannot confidently identify it at all, do NOT force it into
    "labs" — put it in "unknown_items" instead (per the anti-
    hallucination rule).
- "matched_text" must be the actual raw text you read, as written.

====================
STEP 4: DOCUMENT CLASSIFICATION
====================
Determine the document_type using these criteria:

- "lab_prescription": a medical document requesting lab tests — this
  includes BOTH prescriptions with checkbox/checklist panels (printed
  test names next to boxes/circles to mark) AND prescriptions where
  tests are simply handwritten/typed as free text, with or without a
  doctor's signature/stamp. The presence of a checkbox panel (checked or
  not) is a STRONG signal this is a lab_prescription, but its absence
  does not rule it out if lab tests are written as plain text instead.
- "medical_report": contains lab RESULTS/values already filled in (not a
  request for tests), e.g. a completed report with numeric results next
  to test names.
- "radiology_request": requests imaging studies (X-Ray, CT, MRI,
  Ultrasound) rather than lab tests — even if it also has a
  checkbox-style layout.
- "advertisement": promotional/marketing content, not a real
  patient-specific medical document.
- "invoice": a bill/receipt/payment document, even if it lists test
  names with prices.
- "blank": the page is empty or contains no meaningful printed/
  handwritten content.
- "other": doesn't fit any category above (e.g. an unrelated document,
  ID card, letterhead only with no medical content, etc.).

Note: the presence of checkbox panels by itself does NOT automatically
mean tests were REQUESTED — that determination is made separately in
STEP 2 (per-checkbox mark verification). document_type here only
classifies what KIND of document this is, independent of which boxes (if
any) are actually checked.

Also set "is_spam" (boolean): true if document_type is "advertisement",
"invoice", "blank", or "other" — i.e. this is not a genuine
patient-specific medical document at all. false for "lab_prescription",
"medical_report", or "radiology_request".

====================
STEP 5: JSON OUTPUT STRUCTURE
====================
Return ONLY valid JSON.
{
    "raw_transcription": "...",
    "document_type": "lab_prescription",
    "is_prescription": true,
    "is_spam": false,
    "total_tests_detected": 5,
    "labs": [
        {
            "standardized_name": "...",
            "matched_text": "...",
            "confidence": 40,
            "source": "checkbox"
        }
    ],
    "unknown_items": [
        "raw ambiguous text 1"
    ],
    "notes": "..."
}
"""
def analyze_prescription(image_path: str) -> dict:
    """
    Single Gemini multimodal call that classifies the image AND extracts
    lab tests in one pass.

    Args:
        image_path: Absolute path to the prescription image on disk.

    Returns:
        dict with keys: document_type, is_prescription, is_spam, is_error,
        overall_confidence, process_success, labs, unknown_items, notes.
        Always returns a safe dict even on failure.
    """
    def _safe_error(notes: str) -> dict:
        """
        Used ONLY for technical/system failures (missing key, unreadable
        image, API exception, bad JSON) — NOT for the model genuinely
        deciding a document is spam. Keeping these separate means a
        transient Gemini outage no longer gets silently mislabeled and
        discarded as "spam"; callers can detect is_error and retry / queue
        for manual review instead of rejecting the document outright.
        """
        return {
            "document_type":      "other",
            "is_prescription":    False,
            "is_spam":            False,
            "is_error":           True,
            "overall_confidence": 0,
            "process_success":    False,
            "labs":               [],
            "unknown_items":      [],
            "ocr_usage":          None,
            "notes":              notes,
        }

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        notes = (
            "Gemini API key not configured "
            "(set GEMINI_API_KEY or GOOGLE_API_KEY)."
        )
        logger.error("[OCR] %s", notes)
        from notified_center import send_production_alert
        send_production_alert(
            subject="OCR Missing Gemini API Key",
            body_or_error=notes,
            context={"image_path": image_path},
            level="CRITICAL",
        )
        return _safe_error(notes)

    # ── Load image ────────────────────────────────────────────────────────────
    try:
        img = Image.open(image_path)
    except Exception as exc:
        notes = f"Failed to open image: {exc}"
        logger.error("[OCR] %s", notes)
        from notified_center import send_production_alert
        send_production_alert(
            subject="OCR Image Load Failure",
            body_or_error=exc,
            context={"image_path": image_path},
        )
        return _safe_error(notes)

    # ── Single Gemini call ────────────────────────────────────────────────────
    try:
        gemini_client = genai.Client(api_key=api_key)

        start = time.time()
        response = gemini_client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[img, _PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(
                    thinking_level="minimal",
                ),
            ),
        )
        elapsed_ms = round((time.time() - start) * 1000, 2)

        usage = response.usage_metadata
        ocr_usage = {
            "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
            "total_tokens": getattr(usage, "total_token_count", 0) or 0,
        } if usage else None

        logger.info(
            "[OCR] done | time=%s ms | in=%s | out=%s | total=%s",
            elapsed_ms,
            usage.prompt_token_count if usage else 0,
            usage.candidates_token_count if usage else 0,
            usage.total_token_count if usage else 0,
        )

    except Exception as exc:
        notes = f"Gemini API call failed: {exc}"
        logger.exception("❌ [OCR] %s", notes)
        from notified_center import send_production_alert
        send_production_alert(
            subject="OCR Gemini Vision Call Failure",
            body_or_error=exc,
            context={"image_path": image_path},
        )
        return _safe_error(notes)

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        data = json.loads(response.text)
    except Exception as exc:
        notes = f"JSON parse error: {exc} | raw: {response.text[:200]}"
        logger.exception("❌ [OCR] %s", notes)
        from notified_center import send_production_alert
        send_production_alert(
            subject="OCR JSON Parse Failure",
            body_or_error=exc,
            context={"image_path": image_path, "raw_response": getattr(response, "text", "")[:500]},
        )
        return _safe_error(notes)

    # This response reflects a real (if possibly low-confidence) model
    # judgement, so it is NOT a technical error.
    data["is_error"] = False
    data["ocr_usage"] = ocr_usage
    data.setdefault("is_spam", not data.get("is_prescription", False))

    # ── Calculate Overall Confidence Mathematically ────────────────────────────
    labs = data.get("labs", [])
    unknown_items = data.get("unknown_items", [])

    llm_total = data.get("total_tests_detected", 0)
    actual_extracted = len(labs) + len(unknown_items)
    total_detected = max(llm_total, actual_extracted, 1)  # avoid div-by-zero

    extraction_ratio = len(labs) / total_detected
    extraction_ratio = min(extraction_ratio, 1.0)  # never exceed 100%

    if labs:
        avg_item_confidence = sum(lab.get("confidence", 0) for lab in labs) / len(labs)
    else:
        avg_item_confidence = 0

    if data.get("is_prescription"):
        overall_confidence = int(extraction_ratio * avg_item_confidence)
    else:
        overall_confidence = 0

    process_success = overall_confidence >= CONFIDENCE_THRESHOLD
    data["overall_confidence"] = overall_confidence
    data["process_success"] = process_success

    lab_items_log = [
        f"     • {l.get('standardized_name', '')} (matched: '{l.get('matched_text', '')}', conf: {l.get('confidence', 0)}%, src: {l.get('source', '')})"
        for l in labs
    ]
    labs_str = "\n".join(lab_items_log) if lab_items_log else "     • (None)"

    logger.info(
        "\n" + "="*80 + "\n"
        "📸 [OCR SCAN COMPLETE]\n"
        "   Image:            %s\n"
        "   Document Type:    %s\n"
        "   Is Prescription:  %s | Is Spam: %s\n"
        "   Detected Count:   %d | Extracted Labs: %d | Unknowns: %d\n"
        "   Extracted Tests:\n%s\n"
        "   Confidence Math:  %d%% (Completeness: %.2f * Avg Quality: %.1f%%)\n"
        "   Decision:         %s (Threshold: %d%%)\n"
        "   Token Usage:      In: %d | Out: %d | Time: %s ms\n"
        + "="*80,
        os.path.basename(image_path),
        data.get("document_type", "unknown"),
        data.get("is_prescription"),
        data.get("is_spam"),
        total_detected,
        len(labs),
        len(unknown_items),
        labs_str,
        overall_confidence,
        extraction_ratio,
        avg_item_confidence,
        "AUTOMATED FLOW" if process_success else ("MANUAL REVIEW QUEUE" if data.get("is_prescription") else "SPAM / REJECT"),
        CONFIDENCE_THRESHOLD,
        ocr_usage.get("input_tokens", 0) if ocr_usage else 0,
        ocr_usage.get("output_tokens", 0) if ocr_usage else 0,
        elapsed_ms,
    )

    return data


# ---------------------------------------------------------------------------
# Backwards-compat shim so existing imports of classify_prescription still work
# ---------------------------------------------------------------------------
def classify_prescription(image_path: str) -> dict:
    """
    Legacy wrapper kept for import compatibility.
    Internally calls analyze_prescription() and maps the result to the
    old shape: { "classification", "confidence", "reason" }.
    """
    result = analyze_prescription(image_path)
    return {
        "classification": "prescription" if result.get("is_prescription") else "spam",
        "confidence":     result.get("overall_confidence", 0) / 100.0,
        "reason":         result.get("notes", ""),
    }