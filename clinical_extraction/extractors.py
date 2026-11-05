"""Rule-based extractors working on plain text: measurements (lab results, vital signs), medications,
conditions/symptoms and dates. Every Evidence they return is a verbatim span of the input text."""

import re
from dataclasses import dataclass

from clinical_extraction import normalize as nz
from clinical_extraction.context import condition_assertion, medication_assertion, sentence_for, sentence_spans
from clinical_extraction.lexicon import (
    CONDITION_ENTRIES,
    KIND_CONDITION,
    KIND_LAB,
    KIND_SYMPTOM,
    MEASUREMENT_ENTRIES,
    MEDICATION_ENTRIES,
    SYMPTOM_ENTRIES,
    LexEntry,
)
from clinical_extraction.models import (
    ENTITY_CONDITION,
    ENTITY_DATE,
    ENTITY_LAB_RESULT,
    ENTITY_MEDICATION,
    ENTITY_SYMPTOM,
    ENTITY_VITAL_SIGN,
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_SOURCE_PRINTED,
    FLAG_SOURCE_RANGE,
    Evidence,
)

M_MEASURE = "rule_measurement_inline_v1"
M_MEDICATION = "lexicon_medication_v1"
M_CONDITION = "lexicon_condition_v1"
M_SYMPTOM = "lexicon_symptom_v1"
M_DATE = "rule_date_v1"


# ---------------------------------------------------------------- lexicon matcher

def _is_abbreviation(term: str) -> bool:
    """Case-sensitive terms: short all-capital abbreviations (ALT, CKD, T2DM) and 'Na'."""
    return " " not in term and ((term.isupper() and len(term) <= 6) or term == "Na")


def _term_pattern(term: str) -> str:
    body = r"\s+".join(re.escape(part) for part in term.split())
    return body if _is_abbreviation(term) else f"(?i:{body})"


class LexiconMatcher:
    """Finds lexicon terms in text, longest term first, never overlapping."""

    def __init__(self, entries: tuple[LexEntry, ...]) -> None:
        self._by_key: dict[str, LexEntry] = {}
        terms: list[str] = []
        for entry in entries:
            for term in entry.terms:
                self._by_key[re.sub(r"\s+", " ", term.casefold())] = entry
                terms.append(term)
        terms.sort(key=len, reverse=True)
        alternation = "|".join(_term_pattern(t) for t in terms)
        self._pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])")

    def find(self, text: str, start: int = 0, end: int | None = None):
        """Yield (match, entry)."""
        for m in self._pattern.finditer(text, start, len(text) if end is None else end):
            yield m, self._by_key[re.sub(r"\s+", " ", m.group(0).casefold())]

    def lookup(self, text: str) -> LexEntry | None:
        return self._by_key.get(re.sub(r"\s+", " ", text.strip().casefold()))


MEASUREMENT_MATCHER = LexiconMatcher(MEASUREMENT_ENTRIES)
MEDICATION_MATCHER = LexiconMatcher(MEDICATION_ENTRIES)
CONDITION_MATCHER = LexiconMatcher(CONDITION_ENTRIES)
SYMPTOM_MATCHER = LexiconMatcher(SYMPTOM_ENTRIES)


# ---------------------------------------------------------------- measurements
_GAP = r"(?:[\s:=\(|]|\b(?:was|is|of|at|measured|level|levels|value|result|returned|reading|came\s+back)\b)*"
_VALUE = re.compile(
    rf"(?P<gap>{_GAP})(?P<cmp><=|>=|[<>]|≤|≥)?\s*(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:[.,]\d{{1,4}})?)(?![\d/]|-\d|:\d)"
)
_BP_VALUE = re.compile(rf"(?P<gap>{_GAP})(?P<sys>\d{{2,3}})\s*/\s*(?P<dia>\d{{2,3}})(?![\d/])")
_UNIT_AFTER = re.compile(rf"[\s|]*(?P<unit>{nz.LAB_UNIT_PATTERN})(?![A-Za-z0-9])", re.I)
_TEMP_UNIT_AFTER = re.compile(r"\s*(?P<unit>°\s?[CF]|[CF])(?![A-Za-z0-9])")
_FLAG_AFTER = re.compile(r"[\s|]*\(?(?P<flag>HH|LL|H|L|High|Low|Critical)\)?(?![A-Za-z0-9])")
_REF_AFTER = re.compile(
    r"[\s|]*[\(\[]?\s*(?:ref(?:erence)?(?:\s*range)?|normal|range)?\s*[:=]?\s*"
    r"(?:(?P<lo>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?P<hi>\d+(?:\.\d+)?)(?![\d\-/.]\d)|(?P<rc>[<>]=?)\s*(?P<rv>\d+(?:\.\d+)?))\s*[\)\]]?"
)
_NEXT_WORD = re.compile(r"[\s|]*(?P<w>[A-Za-z]{2,})")
_OK_NEXT_WORDS = {
    "on", "at", "and", "with", "ref", "reference", "normal", "range", "high", "low", "flag", "from", "taken", "collected",
    "today", "previously", "was", "which", "while", "but", "in", "last", "prior", "down", "up", "compared", "vs", "by",
}


def _plausibility(entry: LexEntry, value: float, unit: str | None) -> bool | None:
    rng = entry.plausible.get(unit) or entry.plausible.get("*")
    if rng is None:
        return None
    return rng[0] <= value <= rng[1]


def _line_end(text: str, position: int) -> int:
    nl = text.find("\n", position)
    return len(text) if nl < 0 else nl


def parse_measurement_tail(entry: LexEntry, tail: str) -> dict | None:
    """Parse '<gap> value [unit] [flag] [reference]' starting right after a test name. Returns the parsed fields
    plus `consumed` (characters of `tail` that belong to the mention: gap, value, unit and flag, not the reference)
    or None when this is not a result."""
    is_bp = entry.name == "Blood pressure"
    out: dict = {}
    if is_bp:
        m = _BP_VALUE.match(tail)
        if not m:
            return None
        sys_, dia = int(m["sys"]), int(m["dia"])
        if not (50 <= sys_ <= 300 and 20 <= dia <= 200 and sys_ > dia):
            return None
        out.update(value_text=f"{m['sys']}/{m['dia']}", value_numeric=float(sys_), comparator=None,
                   attributes={"systolic": sys_, "diastolic": dia})
    else:
        m = _VALUE.match(tail)
        if not m:
            return None
        number = nz.parse_number(m["num"])
        if number is None:
            return None
        cmp_ = {"≤": "<=", "≥": ">="}.get(m["cmp"], m["cmp"])
        out.update(value_text=m["num"], value_numeric=number, comparator=cmp_, attributes={})
    pos = m.end()

    unit_text = unit = None
    um = _UNIT_AFTER.match(tail, pos)
    if um is None and entry.name == "Temperature":
        um = _TEMP_UNIT_AFTER.match(tail, pos)
    if um:
        unit_text = um["unit"]
        unit = nz.normalize_unit(unit_text)
        pos = um.end()
        if entry.units and unit not in entry.units:
            return None  # e.g. "Calcium 500 mg" is a supplement dose, not a calcium result
    elif entry.unit_required:
        return None
    out.update(unit_text=unit_text, unit_normalized=unit)

    flag = None
    fm = _FLAG_AFTER.match(tail, pos)
    if fm:
        flag = fm["flag"]
        pos = fm.end()
    if unit is None and flag is None and not is_bp:
        nxt = _NEXT_WORD.match(tail, pos)
        same_line = nxt is not None and "\n" not in tail[pos:nxt.start("w")]
        if nxt and same_line and nxt["w"].lower() not in _OK_NEXT_WORDS:
            return None  # "Sodium 2 grams restriction": a number followed by an unrelated word
    mention_len = pos

    ref_text = lo = hi = None
    rm = _REF_AFTER.match(tail, pos)
    if rm:
        if rm["lo"] is not None:
            lo_v, hi_v = float(rm["lo"]), float(rm["hi"])
            if lo_v < hi_v:
                lo, hi, ref_text = lo_v, hi_v, tail[pos:rm.end()].strip(" \t\r\n|([)]")
        else:
            ref_text = tail[pos:rm.end()].strip(" \t\r\n|([)]")
            if rm["rc"].startswith("<"):
                hi = float(rm["rv"])
            else:
                lo = float(rm["rv"])
    out.update(reference_text=ref_text, reference_low=lo, reference_high=hi, flag_text=flag, consumed=mention_len)
    return out


def _flag_fields(parsed: dict, is_bp: bool) -> tuple[str | None, str | None]:
    flag_text = parsed.get("flag_text")
    if flag_text:
        word = flag_text.lower()
        if word in ("h", "hh", "high", "critical"):
            return FLAG_HIGH, FLAG_SOURCE_PRINTED
        if word in ("l", "ll", "low"):
            return FLAG_LOW, FLAG_SOURCE_PRINTED
    value = parsed.get("value_numeric")
    if is_bp or value is None or parsed.get("comparator"):
        return None, None
    lo, hi = parsed.get("reference_low"), parsed.get("reference_high")
    if lo is not None and hi is not None:
        if value < lo:
            return FLAG_LOW, FLAG_SOURCE_RANGE
        if value > hi:
            return FLAG_HIGH, FLAG_SOURCE_RANGE
        return FLAG_NORMAL, FLAG_SOURCE_RANGE
    return None, None


def build_measurement(entry: LexEntry, parsed: dict) -> Evidence:
    """Evidence skeleton (no text/offsets/modality yet) from a parsed measurement."""
    is_bp = entry.name == "Blood pressure"
    unit = parsed["unit_normalized"]
    attributes = dict(parsed["attributes"])
    plausible = None if is_bp else _plausibility(entry, parsed["value_numeric"], unit)
    if plausible is False:
        attributes["implausible_value"] = True
    flag, flag_source = _flag_fields(parsed, is_bp)
    ev = Evidence(
        entity_type=ENTITY_LAB_RESULT if entry.kind == KIND_LAB else ENTITY_VITAL_SIGN,
        entity_name=entry.name,
        mention_text="",
        source_text="",
        modality="",
        extraction_method=M_MEASURE,
        value_text=parsed["value_text"],
        value_numeric=parsed["value_numeric"],
        value_comparator=parsed["comparator"],
        unit_text=parsed["unit_text"],
        unit_normalized=unit,
        reference_text=parsed["reference_text"],
        reference_low=parsed["reference_low"],
        reference_high=parsed["reference_high"],
        abnormal_flag=flag,
        flag_source=flag_source,
        attributes=attributes,
    )
    return ev


def _cover_mention(text: str, ev: Evidence) -> None:
    """Make sure the stored sentence contains the whole mention (a mention can continue on the next line)."""
    if ev.source_end is not None and ev.char_end is not None and ev.char_end > ev.source_end:
        ev.source_end = _line_end(text, ev.char_end - 1)
        ev.source_text = text[ev.source_start:ev.source_end].rstrip()
        ev.source_end = ev.source_start + len(ev.source_text)


def extract_measurements(text: str, spans: list[tuple[int, int]]) -> list[Evidence]:
    found: list[Evidence] = []
    for m, entry in MEASUREMENT_MATCHER.find(text):
        tail = text[m.end():m.end() + 200]  # may continue on following lines (one table cell per line)
        parsed = parse_measurement_tail(entry, tail)
        if parsed is None:
            continue
        ev = build_measurement(entry, parsed)
        start, end = m.start(), m.end() + parsed["consumed"]
        sentence = sentence_for(spans, m.start())
        ev.char_start, ev.char_end = start, end
        ev.mention_text = text[start:end]
        if sentence:
            ev.source_start, ev.source_end = sentence
            ev.source_text = text[sentence[0]:sentence[1]]
        else:
            ev.source_text = ev.mention_text
        _cover_mention(text, ev)
        found.append(ev)
    return found


# ---------------------------------------------------------------- medications
_DOSE = re.compile(rf"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{nz.DOSE_UNIT_PATTERN})(?![A-Za-z0-9])", re.I)
_DOSE_BEFORE = re.compile(rf"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{nz.DOSE_UNIT_PATTERN})\s+(?:of\s+)?$", re.I)
_SENTENCE_STOP = re.compile(r"[.;](?:\s|$)")
_DURATION = re.compile(r"\bfor\s+(?P<n>\d{1,3})\s+(?P<u>days?|weeks?|months?)\b", re.I)


def extract_medications(text: str, spans: list[tuple[int, int]]) -> list[Evidence]:
    matches = list(MEDICATION_MATCHER.find(text))
    found: list[Evidence] = []
    for index, (m, entry) in enumerate(matches):
        sentence = sentence_for(spans, m.start())
        s_start, s_end = sentence if sentence else (m.start(), m.end())
        limit = min(len(text), m.end() + 90)
        stop = _SENTENCE_STOP.search(text, m.end(), limit)
        if stop:
            limit = stop.start()
        if index + 1 < len(matches) and matches[index + 1][0].start() < limit:
            limit = matches[index + 1][0].start()
        window = text[m.end():limit]
        attributes: dict = {}
        mention_end = m.end()
        value_text = unit_text = unit_norm = None
        value_numeric = None

        dm = _DOSE.search(window)
        dose_span = None
        if dm and dm.start() <= 40:
            dose_span = (m.end() + dm.start(), m.end() + dm.end())
        else:
            before = text[max(s_start, m.start() - 25):m.start()]
            bm = _DOSE_BEFORE.search(before)
            if bm:
                dm = bm
                dose_span = (m.start() - (len(before) - bm.start()), m.start() - (len(before) - bm.end()))
        if dm and dose_span:
            value_text = text[dose_span[0]:dose_span[1]]
            value_numeric = float(dm["num"])
            unit_text = dm["unit"]
            unit_norm = nz.normalize_unit(unit_text)
            if dose_span[0] >= m.end():
                mention_end = max(mention_end, dose_span[1])
        start = min(m.start(), dose_span[0]) if dose_span and dose_span[1] <= m.start() else m.start()

        freq = nz.find_frequency(window)
        if freq:
            fm, normalized, times, prn = freq
            attributes.update(frequency_text=fm.group(0), frequency_normalized=normalized, times_per_day=times,
                              as_needed=prn)
            mention_end = max(mention_end, m.end() + fm.end())
        route = nz.find_route(window) or nz.find_route(text[max(s_start, m.start() - 15):m.start()])
        if route:
            attributes["route"] = route[1]
            attributes["route_text"] = route[0].group(0)
        dur = _DURATION.search(window)
        if dur:
            attributes["duration_text"] = dur.group(0)

        assertion = medication_assertion(text[s_start:s_end], m.start() - s_start, m.end() - s_start)
        ev = Evidence(
            entity_type=ENTITY_MEDICATION,
            entity_name=entry.name,
            mention_text=text[start:mention_end],
            source_text=text[s_start:s_end],
            modality="",
            extraction_method=M_MEDICATION,
            char_start=start,
            char_end=mention_end,
            source_start=s_start if sentence else None,
            source_end=s_end if sentence else None,
            assertion=assertion,
            value_text=value_text,
            value_numeric=value_numeric,
            unit_text=unit_text,
            unit_normalized=unit_norm,
            attributes={"matched_name": m.group(0), **attributes},
        )
        _cover_mention(text, ev)
        found.append(ev)
    return found


# ---------------------------------------------------------------- conditions and symptoms

def _extract_lexicon_entities(text, spans, matcher, entity_type, method) -> list[Evidence]:
    found: list[Evidence] = []
    for m, entry in matcher.find(text):
        sentence = sentence_for(spans, m.start())
        s_start, s_end = sentence if sentence else (m.start(), m.end())
        assertion, attrs = condition_assertion(text[s_start:s_end], m.start() - s_start, m.end() - s_start)
        found.append(Evidence(
            entity_type=entity_type,
            entity_name=entry.name,
            mention_text=m.group(0),
            source_text=text[s_start:s_end],
            modality="",
            extraction_method=method,
            char_start=m.start(),
            char_end=m.end(),
            source_start=s_start if sentence else None,
            source_end=s_end if sentence else None,
            assertion=assertion,
            attributes={"matched_name": m.group(0), **attrs},
        ))
    return found


def extract_conditions(text, spans) -> list[Evidence]:
    return _extract_lexicon_entities(text, spans, CONDITION_MATCHER, ENTITY_CONDITION, M_CONDITION)


def extract_symptoms(text, spans) -> list[Evidence]:
    return _extract_lexicon_entities(text, spans, SYMPTOM_MATCHER, ENTITY_SYMPTOM, M_SYMPTOM)


# ---------------------------------------------------------------- dates
_DATE_ROLES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:date\s+of\s+birth|dob|born)\W*$", re.I), "date_of_birth"),
    (re.compile(r"(?:report(?:ed)?\s+date|date\s+of\s+report|reported(?:\s+on)?)\W*$", re.I), "report_date"),
    (re.compile(r"(?:collect(?:ed|ion)(?:\s+date)?|specimen(?:\s+date)?|sample\s+date|drawn)\W*(?:on\W*)?$", re.I), "collection_date"),
    (re.compile(r"(?:admi(?:tted|ssion)(?:\s+date)?|date\s+of\s+admission)\W*(?:on\W*)?$", re.I), "admission_date"),
    (re.compile(r"(?:discharg(?:ed|e)(?:\s+date)?|date\s+of\s+discharge)\W*(?:on\W*)?$", re.I), "discharge_date"),
    (re.compile(r"(?:visit(?:\s+date)?|seen\s+on|consult(?:ation)?(?:\s+date)?|date\s+of\s+(?:visit|service))\W*$", re.I), "visit_date"),
]


def _date_role(text: str, start: int) -> str | None:
    before = text[max(0, start - 40):start]  # the role words must sit immediately before the date
    for pattern, role in _DATE_ROLES:
        if pattern.search(before):
            return role
    return None


def extract_dates(text: str, spans: list[tuple[int, int]]) -> list[Evidence]:
    taken: list[tuple[int, int]] = []
    found: list[Evidence] = []
    candidates = []
    for kind, pattern in nz.DATE_PATTERNS:
        for m in pattern.finditer(text):
            candidates.append((m.start(), -(m.end() - m.start()), kind, m))
    for _, _, kind, m in sorted(candidates, key=lambda c: (c[0], c[1])):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue
        groups = m.groupdict()
        iso, candidates_iso, valid = nz.resolve_date(kind, groups)
        if not valid:
            continue
        taken.append((m.start(), m.end()))
        sentence = sentence_for(spans, m.start())
        s_start, s_end = sentence if sentence else (m.start(), m.end())
        attrs: dict = {"format": kind}
        if iso is None:
            attrs["ambiguous"] = True
            attrs["candidates"] = candidates_iso
        role = _date_role(text, m.start())
        if role:
            attrs["role"] = role
        found.append(Evidence(
            entity_type=ENTITY_DATE,
            entity_name=role or "date",
            mention_text=m.group(0),
            source_text=text[s_start:s_end],
            modality="",
            extraction_method=M_DATE,
            char_start=m.start(),
            char_end=m.end(),
            source_start=s_start if sentence else None,
            source_end=s_end if sentence else None,
            date_text=m.group(0),
            date_iso=iso,
            attributes=attrs,
        ))
    return sorted(found, key=lambda e: e.char_start)


def attach_event_dates(items: list[Evidence]) -> None:
    """A lab/vital/medication gets an event date only when exactly one unambiguous date occurs in the same
    sentence. Nothing is inferred from the rest of the page."""
    dates = [e for e in items if e.entity_type == ENTITY_DATE]
    for ev in items:
        if ev.entity_type in (ENTITY_DATE, ENTITY_CONDITION, ENTITY_SYMPTOM) or ev.source_start is None:
            continue
        same = [d for d in dates if d.source_start == ev.source_start and d.date_iso]
        if len(same) == 1 and not any(d.attributes.get("ambiguous") for d in dates if d.source_start == ev.source_start):
            ev.date_text, ev.date_iso = same[0].date_text, same[0].date_iso
            ev.attributes["date_from"] = "same_sentence"


# ---------------------------------------------------------------- orchestration for plain text

def extract_from_text(text: str) -> list[Evidence]:
    """All entity types from one text. Modality, confidence etc. are filled by `pipeline.extract_text_evidence`."""
    if not text or not text.strip():
        return []
    spans = sentence_spans(text)
    items: list[Evidence] = []
    items += extract_measurements(text, spans)
    items += extract_medications(text, spans)
    items += extract_conditions(text, spans)
    items += extract_symptoms(text, spans)
    items += extract_dates(text, spans)
    attach_event_dates(items)
    items.sort(key=lambda e: (e.char_start if e.char_start is not None else 0, e.entity_type))
    return items
