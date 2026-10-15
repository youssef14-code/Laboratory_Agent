import logging
import mimetypes
import os
import time
from typing import Union

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 🛡️ إعدادات الـ Logger والـ Fallback
try:
    from utils.trace_logger import trace_logger
except ImportError:
    class DummyTraceLogger:
        def start_pipeline(self, *args, **kwargs): pass
        def step(self, *args, **kwargs): pass
        def log_llm_call(self, *args, **kwargs): pass
        def log_output(self, *args, **kwargs): pass
        def end_pipeline(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
    trace_logger = DummyTraceLogger()

logger = logging.getLogger(__name__)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class TestItem(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)


class PrescriptionOCRResult(BaseModel):
    is_prescription: bool
    extracted_text: str
    tests: list[TestItem]


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _detect_mime_type(image_bytes: bytes, file_path: str = None) -> str:
    """Detect image MIME type from magic header bytes or file extension."""
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return "image/webp"
    if file_path:
        guessed_type, _ = mimetypes.guess_type(file_path)
        if guessed_type:
            return guessed_type
    return "image/jpeg"


_shared_genai_client = None

def _get_genai_client() -> genai.Client:
    """Retrieve or instantiate a shared Google GenAI Client singleton."""
    global _shared_genai_client
    if _shared_genai_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment variables.")
        _shared_genai_client = genai.Client(api_key=api_key)
    return _shared_genai_client


# ── System Prompt ─────────────────────────────────────────────────────────────

OCR_SYSTEM_PROMPT = (
    "You are a specialized medical OCR assistant. Your task is to analyze the provided image "
    "and extract laboratory tests or medical investigations requested.\n\n"
    "Instructions:\n"
    "1. Determine `is_prescription`: true if the image is a medical prescription, doctor's order, "
    "or laboratory requisition form. false if it is spam, a selfie, food, an unrelated document, "
    "a receipt, or anything other than a prescription.\n"
    "2. Transcribe the medical text into `extracted_text` exactly as written on the prescription.\n"
    "3. Extract all requested laboratory tests / diagnostic investigations into `tests`.\n"
    "4. For each test, provide its `name` and an individual `confidence` score (0.0 to 1.0) "
    "reflecting the clarity and legibility of that specific test's handwriting/text.\n"
    "5. Do NOT extract patient info, doctor info, medications, notes, or instructions.\n\n"
    "CRITICAL HANDWRITING & NOISE-REDUCTION RULES:\n"
    "- Ignore Pre-printed Paper Branding: Ignore medical pad logos, pharmaceutical drug brand names printed on the header/footer, or table lines on the notepad paper.\n"
    "- Handle Lines & Scribbles: Ignore decorative underlines, stray pen marks, background noise, or paper stains. Pay attention to lines or checkmarks ONLY if they explicitly cross out a test (canceled) or check/circle a specific item.\n"
    "- Medical Context Awareness: Leverage standard medical context to decode cursive handwriting and common medical lab abbreviations (e.g., 'TSH', 'FBS', 'Lipid Profile', 'CBC'). However, do NOT hallucinate tests that are not present.\n"
    "- Unreadable Text: If a handwritten test name is completely illegible or heavily crossed out, assign a low confidence score (< 0.4) and do not force an inaccurate guess."
)


def analyze_prescription_image(
    image_path_or_bytes: Union[str, bytes, os.PathLike],
) -> tuple[PrescriptionOCRResult, dict[str, int]]:
    """
    Layer 1 OCR: Takes an image path or raw bytes, sends it to Gemini multimodally,
    and returns a validated PrescriptionOCRResult along with token usage.
    """
    file_path = None
    if isinstance(image_path_or_bytes, (str, os.PathLike)):
        file_path = str(image_path_or_bytes)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Prescription image not found at: {file_path}")
        with open(file_path, "rb") as f:
            image_bytes = f.read()
    elif isinstance(image_path_or_bytes, (bytes, bytearray)):
        image_bytes = bytes(image_path_or_bytes)
    else:
        raise TypeError(f"Expected str, PathLike, or bytes, got {type(image_path_or_bytes)}")

    if not image_bytes:
        raise ValueError("Prescription image content is empty.")

    mime_type = _detect_mime_type(image_bytes, file_path)
    client = _get_genai_client()
    model_name = "gemini-3.6-flash"

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    logger.info(
        "🔬 [OCR] Calling Gemini model=%s | mime_type=%s | bytes_len=%d",
        model_name, mime_type, len(image_bytes),
    )
    trace_logger.start_pipeline("OCR PIPELINE")
    trace_logger.step(
        "Gemini Multimodal OCR Call",
        input_data={
            "model": model_name,
            "mime_type": mime_type,
            "image_bytes_len": len(image_bytes),
            "source": file_path or "bytes",
        },
    )

    ocr_start = time.time()
    response = client.models.generate_content(
        model=model_name,
        contents=[image_part, OCR_SYSTEM_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PrescriptionOCRResult,
            temperature=0.0,
            thinking_config=types.ThinkingConfig(
                thinking_level="minimal",
            ),
        ),
    )
    ocr_duration = time.time() - ocr_start

    ocr_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        ocr_usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        ocr_usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        ocr_usage["total_tokens"] = getattr(response.usage_metadata, "total_token_count", 0) or 0

    if hasattr(response, "parsed") and isinstance(response.parsed, PrescriptionOCRResult):
        result = response.parsed
    elif response.text:
        result = PrescriptionOCRResult.model_validate_json(response.text)
    else:
        trace_logger.end_pipeline("OCR PIPELINE")
        raise ValueError("Gemini returned an empty response for prescription OCR.")

    logger.info(
        "🔬 [OCR] Completed: is_prescription=%s | tests_count=%d | total_tokens=%d",
        result.is_prescription, len(result.tests), ocr_usage["total_tokens"],
    )

    trace_logger.log_llm_call(
        model=model_name,
        duration=ocr_duration,
        input_tokens=ocr_usage["input_tokens"],
        output_tokens=ocr_usage["output_tokens"],
        call_type="ocr_multimodal",
    )
    trace_logger.log_output({
        "is_prescription": result.is_prescription,
        "tests_found": len(result.tests),
        "tests": [f"{t.name} ({t.confidence:.2f})" for t in result.tests],
        "total_tokens": ocr_usage["total_tokens"],
    })
    trace_logger.end_pipeline("OCR PIPELINE")

    return result, ocr_usage