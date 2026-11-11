"""Question understanding (rule-based; no model, no generation).

Turns a free-text question into a structured QuestionAnalysis: question types, clinical entities (canonical names from
the Phase 5 lexicon, synonyms and abbreviations resolved), dates / periods, recency, page hint, stated value
constraints, what is being requested, and out-of-scope flags. Every type records the words that triggered it.
It never guesses: an unrecognised question is "unclassified" and an unrecognised entity is simply absent.
"""

import re

from clinical_extraction import lexicon as lx
from clinical_extraction import normalize as nz
from evidence_reasoning.types import (
    Q_COMPARISON,
    Q_ENTITY,
    Q_RELATIONSHIP,
    Q_SUMMARY,
    Q_TEMPORAL,
    Q_UNCLASSIFIED,
    Q_VALUE,
    QUESTION_TYPES,
    QuestionAnalysis,
    ValueConstraint,
)
from hybrid_retrieval import analyze_query

_KIND_TO_TYPE = {lx.KIND_LAB: "lab_result", lx.KIND_VITAL: "vital_sign", lx.KIND_MEDICATION: "medication",
                 lx.KIND_CONDITION: "condition", lx.KIND_SYMPTOM: "symptom"}
ENTITY_TYPE_OF: dict[str, str] = {
    e.name: _KIND_TO_TYPE[e.kind]
    for entries in (lx.MEASUREMENT_ENTRIES, lx.MEDICATION_ENTRIES, lx.CONDITION_ENTRIES, lx.SYMPTOM_ENTRIES) for e in entries
}


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_COMPARISON = _rx(r"\b(compare[ds]?|comparison|versus|vs\.?|differences?|differ(?:s|ed)?|chang(?:e|ed|es|ing)|increas(?:e|ed|es|ing)|"
                  r"decreas(?:e|ed|es|ing)|rose|fell|dropp?(?:ed)?|trend|over time|improv(?:e|ed|ement)|worsen(?:ed|ing)?|progress(?:ion)?)\b")
_RELATIONSHIP = _rx(r"\b(related to|relationship|relation between|associated with|association|linked to|link between|connected|"
                    r"because of|caused?|causes|due to|resulted? from|prescribed for|used (?:for|to treat)|taken for|indicated for|"
                    r"reason for|why)\b")
_SUMMARY = _rx(r"\b(summar(?:y|ize|ise)|overview|list|all|every|history|findings|tell me about|everything)\b")
_VALUE = _rx(r"\b(values?|levels?|results?|readings?|measurements?|dos(?:e|es|age)|how (?:high|low|much|many)|scores?)\b")
_WHEN = _rx(r"^\s*when\b|\bwhat (?:date|day|time)\b|\bdate of\b")
_TEMPORAL_WORDS = _rx(r"\b(when|before|after|since|until|prior to|following|at the time)\b")
_YES_NO = _rx(r"^\s*(is|are|was|were|does|do|did|has|have|had|can|could|will|would)\b")
_WH_START = _rx(r"^\s*(what|which|how)\b")
_ADVICE = _rx(r"\b(should (?:i|he|she|they|we|the patient)|what should|recommend(?:ed|ation|ations)?|advice|advise|suggest(?:ed)?|"
              r"how (?:to|do i|can i) (?:treat|cure|manage|lower|reduce)|is it safe|can i (?:take|stop|increase|skip)|best treatment|"
              r"cure|prognosis|life expectancy|will (?:he|she|they|the patient) (?:die|recover|survive)|do i have|diagnose|what is wrong)\b")
_FOCUS = (("family_history", _rx(r"\b(family history|father|mother|sibling|parents?)\b")),
          ("allergy", _rx(r"\ballerg\w*")),
          ("discontinued", _rx(r"\b(discontinu\w*|stopp?ed|no longer)\b")),
          ("planned", _rx(r"\b(planned|scheduled|to start)\b")))
_TYPE_WORDS = (("medication", _rx(r"\b(medications?|drugs?|medicines?|prescriptions?)\b")),
               ("lab_result", _rx(r"\b(lab(?:oratory)? (?:tests?|results?|values?)|labs|tests)\b")),
               ("vital_sign", _rx(r"\b(vitals?|vital signs?)\b")),
               ("symptom", _rx(r"\bsymptoms?\b")),
               ("condition", _rx(r"\b(conditions?|diagnos(?:is|es)|diseases?)\b")))
_CMP_WORDS = {"above": ">", "over": ">", "greater than": ">", "more than": ">", "higher than": ">", "exceed": ">", "exceeds": ">",
              "exceeded": ">", "exceeding": ">", "below": "<", "under": "<", "less than": "<", "lower than": "<",
              "at least": ">=", "no less than": ">=", "at most": "<=", "no more than": "<=", "equal to": "=", "equals to": "=",
              "equal": "=", "exactly": "=", ">=": ">=", "<=": "<=", ">": ">", "<": "<"}
_UNIT = rf"(?:{nz.LAB_UNIT_PATTERN}|{nz.DOSE_UNIT_PATTERN})"
_NUM = r"\d+(?:[.,]\d+)?"
_CMP = _rx(rf"(?P<cmp>{'|'.join(re.escape(k) for k in sorted(_CMP_WORDS, key=len, reverse=True))})\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?(?![\w/])")
_BP = _rx(r"\b(?P<sys>\d{2,3})\s*/\s*(?P<dia>\d{2,3})\b")


def _cues(pattern: re.Pattern, text: str) -> list[str]:
    return [m.group(0).strip() for m in pattern.finditer(text)]


def _blank_dates(text: str) -> str:
    """Replace date expressions by spaces so their digits are not read as values."""
    chars = list(text)
    for _kind, pattern in nz.DATE_PATTERNS:
        for m in pattern.finditer(text):
            for i in range(*m.span()):
                chars[i] = " "
    return "".join(chars)


def _unit(raw: str | None) -> str | None:
    return nz.UNIT_LOOKUP.get(raw.strip().lower()) if raw else None


def _value_constraints(text: str, mentions: list[str]) -> list[ValueConstraint]:
    clean = _blank_dates(text)
    found: list[ValueConstraint] = []
    spans: list[tuple[int, int]] = []
    for m in _BP.finditer(clean):
        found.append(ValueConstraint("=", float(m["sys"]), None, float(m["dia"]), m.group(0)))
        spans.append(m.span())
    for m in _CMP.finditer(clean):
        if any(s <= m.start("num") < e for s, e in spans):
            continue
        number = nz.parse_number(m["num"])
        if number is not None:
            found.append(ValueConstraint(_CMP_WORDS[m["cmp"].lower()], number, _unit(m["unit"]), None, m.group(0)))
            spans.append(m.span())
    for mention in mentions:  # a bare number right after an entity: "HbA1c 7.8 %", "HbA1c was 7.8"
        for m in re.finditer(rf"{re.escape(mention)}\s*(?:of|was|is|at|=|:)?\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?(?![\w/])", clean, re.IGNORECASE):
            if any(s <= m.start("num") < e for s, e in spans):
                continue
            number = nz.parse_number(m["num"])
            if number is not None:
                found.append(ValueConstraint("=", number, _unit(m["unit"]), None, m.group(0)))
                spans.append(m.span())
    return found


def understand_question(text: str) -> QuestionAnalysis:
    q = analyze_query(text)  # entities, periods, recency, page hint (shared with Phase 7 retrieval)
    entity_types = {n: ENTITY_TYPE_OF[n] for n in q.entities if n in ENTITY_TYPE_OF}
    cues: dict[str, list[str]] = {}
    notes = list(q.notes)

    yes_no = bool(_YES_NO.search(text))
    wh = bool(_WH_START.search(text))
    when = bool(_WHEN.search(text))
    requested_types = [t for t, rx in _TYPE_WORDS if rx.search(text)]
    requested_types = [t for t in requested_types if t not in entity_types.values() or not q.entities]

    if (c := _cues(_COMPARISON, text)):
        cues[Q_COMPARISON] = c
    if (c := _cues(_RELATIONSHIP, text)):
        cues[Q_RELATIONSHIP] = c
    summary = _cues(_SUMMARY, text) + ([f"plural type word ({', '.join(requested_types)})"] if requested_types and not q.entities else [])
    if summary:
        cues[Q_SUMMARY] = summary
    valued_entity = any(t in ("lab_result", "vital_sign", "medication") for t in entity_types.values())
    value_cues = _cues(_VALUE, text)
    if value_cues or (valued_entity and wh and not yes_no):
        cues[Q_VALUE] = value_cues or ["what/how question about a measured or dosed entity"]
    temporal = (["date/period in question"] if q.periods else []) + ([f"{q.recency} (recency word)"] if q.recency else []) \
        + _cues(_TEMPORAL_WORDS, text)
    if temporal:
        cues[Q_TEMPORAL] = temporal
    if q.entities and (yes_no or not cues):
        cues[Q_ENTITY] = ["yes/no question about a named entity" if yes_no else "named clinical entity"]

    types = [t for t in QUESTION_TYPES if t in cues] or [Q_UNCLASSIFIED]
    primary = types[0]
    if when and primary not in (Q_COMPARISON, Q_RELATIONSHIP, Q_SUMMARY):
        primary = Q_TEMPORAL
        if Q_TEMPORAL not in types:
            types.insert(0, Q_TEMPORAL)

    requested: list[str] = []
    if Q_VALUE in cues:
        requested.append("value")
    value_constraints = _value_constraints(text, q.entity_mentions)
    if value_constraints and "value" not in requested:
        requested.append("value")
    if when:
        requested.append("date")
    if Q_COMPARISON in cues:
        requested.append("change")
    if Q_RELATIONSHIP in cues:
        requested.append("relationship")
    if Q_SUMMARY in cues:
        requested.append("list")
    if Q_ENTITY in cues:
        requested.append("presence")

    focus = next((name for name, rx in _FOCUS if rx.search(text)), None)
    advice = bool(_ADVICE.search(text))
    if advice:
        notes.append("The question asks for advice, a recommendation, a diagnosis or a prediction. This system only checks what "
                     "the documents state and never gives medical advice.")
    if not q.entities and not requested_types:
        notes.append("No clinical entity from the built-in vocabulary was recognised, so entity agreement cannot be checked.")
    if q.periods and len(q.periods) > 1 and not any("ambiguous" in n for n in notes):
        notes.append("More than one date or period was recognised in the question.")
    if Q_RELATIONSHIP in cues and len(q.entities) < 2:
        notes.append("A relationship question needs two named entities; fewer were recognised.")

    return QuestionAnalysis(
        text=text, types=types, primary=primary, cues=cues, entities=list(q.entities), entity_types=entity_types,
        entity_mentions=list(q.entity_mentions), periods=list(q.periods), recency=q.recency, page_hint=q.page_hint,
        value_constraints=value_constraints, requested=requested,
        requested_entity_types=requested_types, assertion_focus=focus, yes_no=yes_no, advice_request=advice, notes=notes)
