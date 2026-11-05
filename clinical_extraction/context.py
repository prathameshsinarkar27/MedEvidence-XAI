"""Sentence segmentation and assertion detection (negation, uncertainty, family history, ...).

NegEx-inspired and rule-based: a small set of trigger phrases is looked for in the part of the sentence before
(and for a few phrases after) a mention, up to a scope boundary. It is deliberately conservative and simple.
"""

import re

from clinical_extraction.models import (
    ASSERT_AFFIRMED,
    ASSERT_ALLERGY,
    ASSERT_DISCONTINUED,
    ASSERT_FAMILY,
    ASSERT_NEGATED,
    ASSERT_PLANNED,
    ASSERT_UNCERTAIN,
)

_TERMINAL = re.compile(r"[.:;!?]\s*$")
_CONT_END = re.compile(r"(?:,|\b(?:and|or|of|with|the|a|an|to|for|in|on|by|at))\s*$", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z])")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence / record line, trimmed of surrounding whitespace, in text order.

    A newline ends a sentence unless the next line clearly continues it (starts lowercase, or the previous line
    ends with a comma or a connecting word)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    lines = text.split("\n")
    chunk_start: int | None = None
    chunk_end = 0
    for index, line in enumerate(lines):
        line_start = pos
        pos += len(line) + 1
        if not line.strip():
            if chunk_start is not None:
                spans.append((chunk_start, chunk_end))
                chunk_start = None
            continue
        stripped_start = line_start + (len(line) - len(line.lstrip()))
        if chunk_start is None:
            chunk_start = stripped_start
        chunk_end = line_start + len(line.rstrip())
        nxt = next((l for l in lines[index + 1:index + 2]), None)
        continues = bool(nxt and nxt.strip() and (nxt.lstrip()[0].islower() or _CONT_END.search(line)))
        if not continues:
            spans.append((chunk_start, chunk_end))
            chunk_start = None
    if chunk_start is not None:
        spans.append((chunk_start, chunk_end))
    # split long chunks at sentence punctuation
    result: list[tuple[int, int]] = []
    for start, end in spans:
        piece = text[start:end]
        last = 0
        for m in _SENT_SPLIT.finditer(piece):
            result.append((start + last, start + m.start()))
            last = m.end()
        result.append((start + last, end))
    return [(s, e) for s, e in result if e > s]


def sentence_for(spans: list[tuple[int, int]], position: int) -> tuple[int, int] | None:
    for start, end in spans:
        if start <= position < end:
            return start, end
    return None


# ---------------------------------------------------------------- assertion
_BOUNDARY = re.compile(r"[;.]|\b(?:but|however|although|except|which|who|while|though)\b", re.I)
_NEG_PRE = re.compile(
    r"\b(?:no|denies|denied|denying|without|negative\s+for|absence\s+of|free\s+of|no\s+evidence\s+of|no\s+signs?\s+of|"
    r"no\s+history\s+of|not\s+have|does\s+not\s+have|did\s+not\s+have|never\s+had|ruled\s+out|neg\s+for)\b",
    re.I,
)
_NEG_POST = re.compile(r"^\W{0,3}(?:was|is|were|has\s+been)?\s*(?:ruled\s+out|absent|not\s+present|negative|not\s+seen|resolved\s+completely)\b", re.I)
_UNC_PRE = re.compile(
    r"\b(?:possible|possibly|probable|probably|suspected|suspect|suspicious\s+for|likely|may\s+have|might\s+have|"
    r"concern\s+for|cannot\s+rule\s+out|can't\s+rule\s+out|rule\s+out|r/o|question\s+of|\?)",
    re.I,
)
_UNC_POST = re.compile(r"^\W{0,3}(?:is|was|are)?\s*(?:suspected|possible|not\s+excluded|cannot\s+be\s+excluded)\b", re.I)
_FAMILY_PRE = re.compile(
    r"\b(?:family\s+history|fh|mother|father|sister|brother|parents?|grandmother|grandfather|aunt|uncle|sibling|siblings)\b",
    re.I,
)
_HISTORICAL_PRE = re.compile(r"\b(?:history\s+of|h/o|past\s+medical\s+history|previous|prior|previously|resolved)\b", re.I)
_ALLERGY_PRE = re.compile(r"\b(?:allergic\s+to|allergy\s+to|allergies|allergy|intoleran(?:t|ce)\s+to|anaphylaxis\s+(?:to|with)|reaction\s+to)\b", re.I)
_DISC_PRE = re.compile(r"\b(?:discontinued|stopped|stop|ceased|held|hold|no\s+longer\s+(?:taking|on)|withdrawn)\b", re.I)
_DISC_POST = re.compile(r"^\W{0,3}(?:was|is|were|has\s+been)?\s*(?:discontinued|stopped|ceased|held|withdrawn)\b", re.I)
_NEG_MED_PRE = re.compile(r"\b(?:not\s+taking|not\s+on|denies\s+taking|never\s+taken|never\s+took|does\s+not\s+take)\b", re.I)
_PLAN_PRE = re.compile(r"\b(?:consider|recommend(?:ed)?|advised?\s+to\s+start|plan\s+to\s+start|plan\s+to|will\s+start|to\s+start|start\s+if|may\s+start)\b", re.I)

_WINDOW_TOKENS = 12


def _scope_before(sentence: str, mention_start: int) -> str:
    """Part of the sentence before the mention, cut at the last scope boundary and limited to a few words."""
    before = sentence[:mention_start]
    last = None
    for m in _BOUNDARY.finditer(before):
        last = m
    if last:
        before = before[last.end():]
    words = before.split()
    return " ".join(words[-_WINDOW_TOKENS:])


def _scope_after(sentence: str, mention_end: int) -> str:
    return sentence[mention_end:mention_end + 40]


def condition_assertion(sentence: str, mention_start: int, mention_end: int) -> tuple[str, dict]:
    """Assertion for a condition or symptom mention. Priority: family history > negated > uncertain > affirmed.
    Returns (assertion, extra_attributes) where attributes may carry temporality='historical'."""
    before = _scope_before(sentence, mention_start)
    after = _scope_after(sentence, mention_end)
    attrs: dict = {}
    if _HISTORICAL_PRE.search(before):
        attrs["temporality"] = "historical"
    if _FAMILY_PRE.search(before):
        return ASSERT_FAMILY, attrs
    if _NEG_PRE.search(before) or _NEG_POST.search(after):
        return ASSERT_NEGATED, attrs
    if _UNC_PRE.search(before) or _UNC_POST.search(after):
        return ASSERT_UNCERTAIN, attrs
    return ASSERT_AFFIRMED, attrs


def medication_assertion(sentence: str, mention_start: int, mention_end: int) -> str:
    """Assertion for a medication mention. Priority: allergy > family > negated > discontinued > planned."""
    before = _scope_before(sentence, mention_start)
    after = _scope_after(sentence, mention_end)
    if _ALLERGY_PRE.search(before):
        return ASSERT_ALLERGY
    if _NEG_MED_PRE.search(before) or re.search(r"\b(?:no|denies|without)\b", before, re.I):
        return ASSERT_NEGATED
    if _DISC_PRE.search(before) or _DISC_POST.search(after):
        return ASSERT_DISCONTINUED
    if _PLAN_PRE.search(before):
        return ASSERT_PLANNED
    if _UNC_PRE.search(before):
        return ASSERT_UNCERTAIN
    return ASSERT_AFFIRMED
