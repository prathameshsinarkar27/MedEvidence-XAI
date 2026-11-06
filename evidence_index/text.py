"""The text that is embedded for one piece of clinical evidence.

Only stored, extracted fields are used: nothing is added, inferred or "improved". The same function is used
at indexing time, and the resulting string is stored next to the vector so that what was embedded can always
be inspected. Changing this function changes `TEXT_VERSION`, which marks existing indexes as stale.
"""

from typing import Any

TEXT_VERSION = "1"
MAX_SOURCE_CHARS = 1000

_ENTITY_LABELS = {
    "lab_result": "Laboratory result",
    "vital_sign": "Vital sign",
    "medication": "Medication",
    "condition": "Condition",
    "symptom": "Symptom",
    "date": "Date",
}
_ASSERTION_LABELS = {
    "negated": "negated (stated as absent)",
    "uncertain": "uncertain",
    "family_history": "family history",
    "allergy": "allergy or intolerance",
    "discontinued": "discontinued",
    "planned": "planned",
}


def build_embedding_text(evidence: Any) -> str:
    """Build the embedding text from an evidence-like object (attribute access; None-safe)."""
    parts: list[str] = [f"{_ENTITY_LABELS.get(evidence.entity_type, evidence.entity_type)}: {evidence.entity_name}."]
    if evidence.value_text:
        value = f"{evidence.value_comparator or ''}{evidence.value_text}"
        unit = evidence.unit_text if evidence.unit_text and evidence.unit_text not in evidence.value_text else None
        parts.append(f"Value: {value}{' ' + unit if unit else ''}.")
    if evidence.reference_text:
        parts.append(f"Reference range: {evidence.reference_text}.")
    if evidence.abnormal_flag and evidence.abnormal_flag != "normal":
        parts.append(f"Flag: {evidence.abnormal_flag}.")
    if evidence.assertion in _ASSERTION_LABELS:
        parts.append(f"Status: {_ASSERTION_LABELS[evidence.assertion]}.")
    when = evidence.date_iso or evidence.date_text
    if when:
        parts.append(f"Date: {when}.")
    source = " ".join((evidence.source_text or "").split())
    if len(source) > MAX_SOURCE_CHARS:
        source = source[:MAX_SOURCE_CHARS].rstrip() + "..."
    if source:
        parts.append(f"Source: {source}")
    return " ".join(parts)
