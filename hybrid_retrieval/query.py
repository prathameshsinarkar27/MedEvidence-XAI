"""Query analysis (rule-based; Phase 8 adds full question understanding).

Extracts only what the ranking needs, using the same vocabularies and date rules as clinical extraction:
entities (canonical names from the clinical lexicon), dates / periods, recency words and a page hint.
Nothing is guessed: an ambiguous numeric date such as 03/04/2026 yields both readings.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

from clinical_extraction import normalize as nz
from clinical_extraction.extractors import (
    CONDITION_MATCHER,
    MEASUREMENT_MATCHER,
    MEDICATION_MATCHER,
    SYMPTOM_MATCHER,
)
from hybrid_retrieval.bm25 import tokenize

_MATCHERS = (MEASUREMENT_MATCHER, MEDICATION_MATCHER, CONDITION_MATCHER, SYMPTOM_MATCHER)
_MONTH_YEAR = re.compile(rf"\b(?P<mon>{nz._MONTH_RE})\b\.?,?\s+(?P<y>\d{{4}})(?!\d)", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:in|during|of|year|since|for)\s+(?P<y>(?:19|20)\d{2})\b", re.IGNORECASE)
_LATEST = re.compile(r"\b(?:latest|most\s+recent|newest|current|currently|last|recent(?:ly)?)\b", re.IGNORECASE)
_EARLIEST = re.compile(r"\b(?:earliest|first|baseline|initial|oldest|original)\b", re.IGNORECASE)
_PAGE = re.compile(r"\bpage\s+(?P<n>\d{1,4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryAnalysis:
    text: str
    tokens: list[str]
    entities: list[str] = field(default_factory=list)  # canonical names, in order of appearance
    entity_mentions: list[str] = field(default_factory=list)  # the words as written in the query
    periods: list[tuple[str, str]] = field(default_factory=list)  # inclusive ISO date ranges
    recency: str | None = None  # "latest" | "earliest" | None
    page_hint: int | None = None
    notes: list[str] = field(default_factory=list)


def _month_range(year: int, month: int) -> tuple[str, str]:
    return date(year, month, 1).isoformat(), date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def _find_entities(text: str) -> tuple[list[str], list[str]]:
    """Longest match wins across all vocabularies ("high blood pressure" is Hypertension, not Blood pressure)."""
    found = [(m.start(), m.end(), entry.name, m.group(0)) for matcher in _MATCHERS for m, entry in matcher.find(text)]
    found.sort(key=lambda f: (-(f[1] - f[0]), f[0]))
    taken: list[tuple[int, int, str, str]] = []
    for start, end, name, mention in found:
        if not any(start < e and s < end for s, e, _, _ in taken):
            taken.append((start, end, name, mention))
    taken.sort()
    names: list[str] = []
    mentions: list[str] = []
    for _, _, name, mention in taken:
        if name not in names:
            names.append(name)
        mentions.append(mention)
    # lower-case abbreviations ("wbc", "hba1c" is already case-insensitive): retry words as upper case
    for word in re.findall(r"[A-Za-z0-9]{2,6}", text):
        if word.isupper():
            continue
        for matcher in _MATCHERS:
            entry = matcher.lookup(word.upper())
            if entry is not None and word.upper() in {t.upper() for t in entry.terms if t.isupper()}:
                if entry.name not in names:
                    names.append(entry.name)
                    mentions.append(word)
    return names, mentions


def analyze_query(text: str) -> QueryAnalysis:
    notes: list[str] = []
    periods: list[tuple[str, str]] = []
    consumed: list[tuple[int, int]] = []

    for kind, pattern in nz.DATE_PATTERNS:
        for m in pattern.finditer(text):
            iso, candidates, valid = nz.resolve_date(kind, m.groupdict())
            if not valid:
                continue
            consumed.append(m.span())
            for c in candidates:
                periods.append((c, c))
            if len(candidates) > 1:
                notes.append(f"'{m.group(0)}' is ambiguous (day/month order); both readings are used")
    for m in _MONTH_YEAR.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        mon = m.group("mon").lower()
        month = nz._MONTHS["sept" if mon.startswith("sept") else mon[:3]]
        year = int(m.group("y"))
        if 1900 <= year <= 2100:
            periods.append(_month_range(year, month))
            consumed.append(m.span())
    for m in _YEAR.finditer(text):
        if any(s <= m.start("y") < e for s, e in consumed):
            continue
        year = int(m.group("y"))
        periods.append((date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()))

    recency = "latest" if _LATEST.search(text) else "earliest" if _EARLIEST.search(text) else None
    if recency and periods:
        notes.append("A date and a recency word were both given; the date is used")
        recency = None
    page = _PAGE.search(text)
    names, mentions = _find_entities(text)
    return QueryAnalysis(
        text=text, tokens=tokenize(text), entities=names, entity_mentions=mentions,
        periods=list(dict.fromkeys(periods)), recency=recency, page_hint=int(page.group("n")) if page else None,
        notes=notes,
    )
