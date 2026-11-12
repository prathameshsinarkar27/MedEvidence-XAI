"""Why was this evidence selected (or not)? Plain sentences built only from the verification facts."""

from evidence_qa.types import CtxEvidence

_RETRIEVAL_LABELS = {"semantic": "text similarity", "keyword": "keyword match", "entity": "entity match", "temporal": "date fit",
                     "confidence": "extraction confidence", "source": "source quality"}
_WHY_NOT = {
    "entity_only_partially_matches": "it only partly matches the entity in the question",
    "assertion_does_not_fit_question": "it is about something other than the patient's own current finding",
    "no_value_stated": "it names the entity but states no value",
    "other_page": "it is on a different page than the one asked about",
    "outside_period": "it is dated outside the requested period",
    "date_unknown": "its date is unknown, so the requested period cannot be confirmed",
    "recency_cannot_be_established": "latest/earliest cannot be established without a date",
    "entity_not_identified": "no entity was identified in the question",
}


def selection_reasons(e: CtxEvidence, conflicting_ids: set[str]) -> list[str]:
    s = e.selection
    out: list[str] = []
    if s.get("retrieval_rank"):
        comps = sorted(((k, v.get("contribution") or 0.0) for k, v in (s.get("retrieval_components") or {}).items()), key=lambda kv: -kv[1])
        top = [_RETRIEVAL_LABELS.get(k, k) for k, c in comps[:2] if c > 0]
        out.append(f"Retrieved at rank {s['retrieval_rank']}" + (f" mainly by {' and '.join(top)}." if top else "."))
    terms = s.get("terms") or {}
    if (terms.get("entity") or {}).get("score") == 1.0:
        out.append(f"Its entity ({e.entity_name}) is the one named in the question.")
    if e.value_text is not None and "value" in (s.get("requested") or []):
        out.append("It states a value, which the question asks for.")
    c = s.get("constraints") or {}
    if c.get("period") == "met":
        out.append(f"Dated {e.date_iso}, inside the requested period.")
    if c.get("recency") == "met":
        out.append(f"It is the {s.get('recency') or 'latest'} dated value of {e.entity_name} in the retrieved evidence.")
    if c.get("page") == "met":
        out.append("It is on the page the question asks about.")
    src = "OCR text" if e.modality in ("ocr", "image_ocr") else "a detected table" if e.modality == "table" else "the document's text layer"
    out.append(f"Source: {src}; extraction confidence {e.extraction_confidence:.2f} (heuristic)"
               + (f"; OCR confidence {e.ocr_confidence:.0f}/100." if e.ocr_confidence is not None else "."))
    if e.role == "supporting":
        out.append(f"Verification score {e.evidence_score:.2f}: direct, in scope and above the supporting threshold.")
    else:
        why = [_WHY_NOT.get(r, r) for r in (s.get("directness_reasons") or [])]
        out.append(f"Verification score {e.evidence_score:.2f}; kept as context, not used as support" + (f" because {'; '.join(why)}." if why else "."))
    if e.id in conflicting_ids:
        out.append("It is involved in a possible contradiction with another evidence item (see the conflicts).")
    return out
