"""
generator.py
Calls Gemini to generate structured knowledge for a Lab/Bundle.
"""

import json
import logging

from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, build_generation_prompt, build_regeneration_prompt
from .schemas import GeneratedKnowledge, KnowledgeGenerationRequest
from .utils import get_gemini_client

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.1-flash-lite"
MAX_RETRIES = 2


def _clean_json_response(raw_text: str) -> dict:
    """Strips markdown fences if the model adds them anyway, then parses JSON."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_gemini(prompt: str) -> dict:
    """
    Calls Gemini and returns the parsed JSON dict.
    Any failure here (network error, blocked/empty response, malformed JSON,
    unexpected client shape, etc.) is logged and re-raised so the caller's
    retry loop can handle it uniformly.
    """
    try:
        client_or_genai = get_gemini_client()
    except Exception as e:
        logger.warning("Could not obtain Gemini client: %s", e)
        raise

    try:
        if hasattr(client_or_genai, "models"):
            response = client_or_genai.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config={"system_instruction": SYSTEM_PROMPT}
            )
        else:
            model = client_or_genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)
            response = model.generate_content(prompt)
    except Exception as e:
        logger.warning("Gemini API call failed: %s", e)
        raise

    raw_text = getattr(response, "text", None)
    if not raw_text:
        # Happens e.g. when the response was blocked by safety filters
        # and has no text candidate at all.
        raise ValueError("Empty response from Gemini (possibly blocked or filtered).")

    try:
        return _clean_json_response(raw_text)
    except json.JSONDecodeError as e:
        logger.warning("Gemini returned malformed JSON: %s | raw: %s", e, raw_text[:300])
        raise


def generate_knowledge(request: KnowledgeGenerationRequest) -> GeneratedKnowledge:
    """
    Calls the LLM to generate knowledge for a new Lab/Bundle.
    Retries a couple of times if the model returns malformed JSON, an
    invalid schema, or the API call itself fails (network/rate-limit/etc.).
    """
    prompt = build_generation_prompt(
        name=request.name,
        patient_instructions=request.patient_instructions,
        duration=request.duration,
        price=request.price,
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            raw = _call_gemini(prompt)
            obj = GeneratedKnowledge(**raw)
            return obj
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning("Generation attempt %s failed (bad output): %s", attempt, e)
        except Exception as e:
            # Covers API/network/rate-limit/client errors too, so a single
            # transient failure doesn't crash the whole pipeline immediately.
            last_error = e
            logger.warning("Generation attempt %s failed (API error): %s", attempt, e)

    raise RuntimeError(f"Failed to generate valid knowledge after retries: {last_error}")


def regenerate_knowledge(
    request: KnowledgeGenerationRequest,
    previous_output: GeneratedKnowledge,
    admin_feedback: str | None = None,
) -> GeneratedKnowledge:
    """Used by the 'Generate Again' button on the Review Page."""
    prompt = build_regeneration_prompt(
        name=request.name,
        patient_instructions=request.patient_instructions,
        duration=request.duration,
        price=request.price,
        previous_output=previous_output.model_dump(),
        admin_feedback=admin_feedback,
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            raw = _call_gemini(prompt)
            return GeneratedKnowledge(**raw)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning("Regeneration attempt %s failed (bad output): %s", attempt, e)
        except Exception as e:
            last_error = e
            logger.warning("Regeneration attempt %s failed (API error): %s", attempt, e)

    raise RuntimeError(f"Failed to regenerate valid knowledge after retries: {last_error}")