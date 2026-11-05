"""Heuristic extraction-confidence score. NOT a probability and NOT calibrated against any ground truth.

score = base(method) adjusted by transparent factors; every factor is returned so the number can be audited.
It measures how structurally complete and unambiguous the rule match was (and how reliable the source text is),
not whether the extraction is clinically correct. Accuracy: Not yet evaluated.
"""

from clinical_extraction.models import (
    ASSERT_AFFIRMED,
    ENTITY_CONDITION,
    ENTITY_DATE,
    ENTITY_LAB_RESULT,
    ENTITY_MEDICATION,
    ENTITY_SYMPTOM,
    ENTITY_VITAL_SIGN,
    MODALITY_IMAGE_OCR,
    MODALITY_OCR,
    MODALITY_TABLE,
    Evidence,
)

BASE = {
    ENTITY_LAB_RESULT: 0.80,
    ENTITY_VITAL_SIGN: 0.80,
    ENTITY_MEDICATION: 0.65,
    ENTITY_CONDITION: 0.70,
    ENTITY_SYMPTOM: 0.70,
    ENTITY_DATE: 0.90,
}
TABLE_HEADER_BONUS = 0.10
UNKNOWN_OCR_FACTOR = 0.70


def score(ev: Evidence) -> tuple[float, dict]:
    factors: dict = {"base": BASE[ev.entity_type]}
    value = BASE[ev.entity_type]

    if ev.extraction_method.endswith("_table_columns_v1"):
        factors["table_header_mapped"] = TABLE_HEADER_BONUS
        value += TABLE_HEADER_BONUS
    if ev.entity_type in (ENTITY_LAB_RESULT, ENTITY_VITAL_SIGN):
        if ev.unit_normalized is None and ev.entity_name not in ("INR",):
            factors["no_unit"] = -0.15
            value -= 0.15
        if ev.attributes.get("implausible_value"):
            factors["implausible_value"] = -0.30
            value -= 0.30
    if ev.entity_type == ENTITY_MEDICATION:
        if ev.value_numeric is not None:
            factors["dose_found"] = 0.10
            value += 0.10
        if ev.attributes.get("frequency_normalized"):
            factors["frequency_found"] = 0.05
            value += 0.05
    if ev.entity_type == ENTITY_DATE and ev.attributes.get("ambiguous"):
        factors["ambiguous_date"] = -0.40
        value -= 0.40
    if ev.entity_type == ENTITY_DATE and ev.attributes.get("format") == "numeric" and ev.date_iso:
        factors["numeric_format"] = -0.10
        value -= 0.10
    if ev.entity_type in (ENTITY_CONDITION, ENTITY_SYMPTOM, ENTITY_MEDICATION) and ev.assertion != ASSERT_AFFIRMED:
        factors["assertion_cue_interpreted"] = -0.05
        value -= 0.05
    if ev.entity_type in (ENTITY_CONDITION, ENTITY_SYMPTOM) and ev.mention_text.isupper() and len(ev.mention_text) <= 6:
        factors["abbreviation"] = -0.10
        value -= 0.10

    if ev.modality in (MODALITY_OCR, MODALITY_IMAGE_OCR):
        if ev.ocr_confidence is None:
            factor = UNKNOWN_OCR_FACTOR
        else:
            factor = 0.6 + 0.4 * max(0.0, min(ev.ocr_confidence, 100.0)) / 100.0
        factors["ocr_text_reliability_multiplier"] = round(factor, 3)
        value *= factor

    value = round(max(0.05, min(value, 0.99)), 2)
    return value, {k: round(v, 3) for k, v in factors.items()}
