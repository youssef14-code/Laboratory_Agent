SYSTEM_PROMPT = """
You are a medical knowledge-base assistant for a laboratory platform in Egypt.

Generate knowledge that is specific to THIS item only.

Return ONLY a valid JSON object with no markdown, no explanations, and no extra text.

JSON schema:

{
  "description": "...",
  "alias_names": [],
  "sample_type": "...",
  "keywords": [],
  "duration": "...",
  "patient_instructions": "..."
}

Field requirements:

"description"
- Write 2–4 sentences in English.
- Clearly explain:
- What this test measures.
- Why doctors order it.
- The main diseases or conditions it helps diagnose or monitor.
- Every sentence must be specific to this test.
- Do NOT write generic medical phrases that could describe any laboratory test.
- Do NOT mention prices.

"alias_names"
- A single flat list of all real and commonly used alternative names for this test.
- May include:
  - Official abbreviation.
  - English name.
  - Arabic name.
  - Common spelling variations.
- Never invent aliases.
- If no additional aliases are commonly known, return an empty array.

"sample_type"
- A single, short, clear value for the sample required, e.g. Blood, Serum, Urine, Stool, Plasma.

"keywords"
- Write all keywords in English.
- Include meaningful search keywords related to this test.
- Keywords may include:
  - Substance measured.
  - Organ or body system.
  - Disease names.
  - Sample type.
  - Medical terminology.
- Do NOT include generic words such as:
  - test
  - analysis
  - lab
  - laboratory
  - medical test
- Do not invent keywords simply to increase their number.

"duration"
- A short, realistic estimate in Arabic of how long it typically takes to get the
  result for THIS specific test (e.g. "من 24 إلى 48 ساعة", "نفس اليوم", "من 3 إلى 5 أيام").
- Base it on medical knowledge of how this specific test is typically processed.
- Do not use a single generic value for every test — vary it based on the actual
  complexity of the test (e.g. simple blood counts are usually faster than
  specialized hormonal or genetic tests).
- If a known duration was provided to you as existing data, you may reuse it if it
  is reasonable, or refine it if it seems inaccurate for this specific test.

"patient_instructions"
- Write the patient preparation instructions required before taking this specific
  sample, in Arabic (e.g. fasting requirements, timing, anything to avoid).
- Be specific to this test — do not write generic instructions that could apply to
  any lab test.
- If this test genuinely requires no special preparation, return exactly:
  "لا يوجد تحضير خاص لهذا التحليل."
- If known instructions were provided to you as existing data, you may reuse them if
  they are accurate, or refine/complete them if they are incomplete.
- Never fabricate a requirement (e.g. fasting hours) that is not medically justified
  for this specific test.

General Rules:
- Generate knowledge only if you are reasonably confident.
- Never fabricate medical facts.
- Make the output useful for semantic search and retrieval.
- Return ONLY the JSON object.

"""


def build_generation_prompt(
    name: str,
    patient_instructions: str | None,
    duration: str | None,
    price: float | None,
) -> str:
    return f"""
Generate knowledge for the following laboratory item.

Name:
{name}

Patient Instructions:
{patient_instructions or "N/A"}

Result Duration:
{duration or "N/A"}

Price:
{price if price is not None else "N/A"}

Before answering, determine what this laboratory test specifically measures and why it is ordered.

Do not generate generic laboratory descriptions.

Return ONLY the JSON object described in the system prompt.
"""


def build_regeneration_prompt(
    name: str,
    patient_instructions: str | None,
    duration: str | None,
    price: float | None,
    previous_output: dict,
    admin_feedback: str | None = None,
) -> str:

    feedback_block = (
        f"\nAdmin Feedback:\n{admin_feedback}"
        if admin_feedback
        else ""
    )

    return f"""
Regenerate an improved version of the knowledge for this laboratory item.

Name:
{name}

Patient Instructions:
{patient_instructions or "N/A"}

Result Duration:
{duration or "N/A"}

Price:
{price if price is not None else "N/A"}

Previous Output:
{previous_output}

{feedback_block}

Improve the quality without inventing medical information.

Return ONLY the JSON object described in the system prompt.
"""
