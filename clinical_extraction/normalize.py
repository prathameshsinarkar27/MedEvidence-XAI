"""Deterministic normalisation helpers: units, numbers, dates, dose frequency, route.

Principles: the original text is always kept by the caller; normalisation only fixes spelling/format (for
example "mg/dl" -> "mg/dL", "12-Aug-2026" -> "2026-08-12"). Values are NEVER converted between units, and
ambiguous input (for example 03/04/2026) is left un-normalised instead of guessed.
"""

import re
from datetime import date

# ---------------------------------------------------------------- units
# canonical spelling -> accepted written variants (matched case-insensitively, whitespace-insensitively)
_UNIT_VARIANTS: dict[str, tuple[str, ...]] = {
    "%": ("%", "percent"),
    "mg/dL": ("mg/dl",),
    "mg/L": ("mg/l",),
    "g/dL": ("g/dl",),
    "g/L": ("g/l",),
    "mmol/L": ("mmol/l",),
    "mmol/mol": ("mmol/mol",),
    "mEq/L": ("meq/l",),
    "µmol/L": ("µmol/l", "μmol/l", "umol/l"),
    "U/L": ("u/l",),
    "IU/L": ("iu/l",),
    "ng/mL": ("ng/ml",),
    "ng/dL": ("ng/dl",),
    "ng/L": ("ng/l",),
    "pg/mL": ("pg/ml",),
    "µg/L": ("µg/l", "μg/l", "ug/l"),
    "pmol/L": ("pmol/l",),
    "nmol/L": ("nmol/l",),
    "mIU/L": ("miu/l",),
    "µIU/mL": ("µiu/ml", "μiu/ml", "uiu/ml"),
    "fL": ("fl",),
    "mm/h": ("mm/hr", "mm/h"),
    "10^9/L": ("10^9/l", "x10^9/l", "x 10^9/l", "10*9/l", "x10*9/l", "10e9/l", "x10e9/l", "10⁹/l"),
    "10^12/L": ("10^12/l", "x10^12/l", "x 10^12/l", "10*12/l", "x10*12/l", "10e12/l", "x10e12/l"),
    "10^3/µL": ("10^3/µl", "10^3/μl", "10^3/ul", "x10^3/ul", "k/µl", "k/μl", "k/ul"),
    "10^6/µL": ("10^6/µl", "10^6/μl", "10^6/ul", "x10^6/ul", "m/µl", "m/ul"),
    "/µL": ("/µl", "/μl", "/ul"),
    "mL/min/1.73 m²": ("ml/min/1.73m2", "ml/min/1.73 m2", "ml/min/1.73m²", "ml/min/1.73 m²"),
    "mmHg": ("mmhg", "mm hg"),
    "bpm": ("bpm", "beats/min", "beats per minute"),
    "/min": ("/min", "per min"),
    "breaths/min": ("breaths/min", "breaths per minute", "br/min"),
    "°C": ("°c", "° c", "deg c", "degrees c", "degc"),
    "°F": ("°f", "° f", "deg f", "degrees f", "degf"),
    "kg": ("kg", "kgs"),
    "lb": ("lb", "lbs"),
    "cm": ("cm",),
    "kg/m²": ("kg/m²", "kg/m2"),
    # medication dose units
    "mg": ("mg",),
    "mcg": ("mcg", "µg", "μg", "ug"),
    "g": ("g",),
    "mL": ("ml",),
    "units": ("unit", "units"),
    "IU": ("iu",),
    "mEq": ("meq",),
}

UNIT_LOOKUP: dict[str, str] = {}
for _canon, _variants in _UNIT_VARIANTS.items():
    for _v in _variants:
        UNIT_LOOKUP[re.sub(r"\s+", "", _v.lower())] = _canon

# Units recognised after a laboratory / vital-sign value (medication dose units are parsed separately because
# short ones such as "g" are only safe next to a drug name). Longest first so "mmol/L" beats "mmol".
_LAB_UNIT_CANONICALS = [c for c in _UNIT_VARIANTS if c not in {"mg", "mcg", "g", "mL", "units", "IU", "mEq"}]
_lab_variants = sorted(
    {v for c in _LAB_UNIT_CANONICALS for v in (*_UNIT_VARIANTS[c],)}, key=len, reverse=True
)
LAB_UNIT_PATTERN = "|".join(re.escape(v).replace(r"\ ", r"\s?") for v in _lab_variants)
# "C"/"F" alone are only accepted for temperature.
TEMP_BARE_UNIT_PATTERN = r"[CF]"

DOSE_UNIT_PATTERN = r"mg|mcg|µg|μg|ug|g|mL|ml|units?|IU|mEq"


def normalize_unit(text: str | None) -> str | None:
    """Canonical spelling of a unit, or None when the text is not a unit this module knows."""
    if not text:
        return None
    key = re.sub(r"\s+", "", text.strip().lower())
    if key in {"c", "f"}:  # bare letters: only meaningful for temperature (handled by the caller)
        return {"c": "°C", "f": "°F"}[key]
    return UNIT_LOOKUP.get(key)


# ---------------------------------------------------------------- numbers
_NUM = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:[.,]\d{1,2})?$|^\d+\.\d+$")


def parse_number(text: str) -> float | None:
    """'7.8' -> 7.8, '1,200' -> 1200.0, '7,8' -> 7.8 (comma + 1-2 digits = decimal comma). None if not a number."""
    text = text.strip()
    if not _NUM.match(text):
        return None
    if re.match(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$", text):
        return float(text.replace(",", ""))
    return float(text.replace(",", "."))


# ---------------------------------------------------------------- dates
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"

DATE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("iso", re.compile(r"(?<![\d\-/.])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d\-/])")),
    ("day_month_name", re.compile(
        rf"(?<![\d\-/.])(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s\-/.]*(?P<mon>{_MONTH_RE})\b\.?,?[\s\-/.]*(?P<y>\d{{4}})(?!\d)",
        re.IGNORECASE)),
    ("month_name_day", re.compile(
        rf"\b(?P<mon>{_MONTH_RE})\b\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})(?!\d)", re.IGNORECASE)),
    ("numeric", re.compile(r"(?<![\d\-/.])(?P<a>\d{1,2})(?P<sep>[/.\-])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4})(?![\d\-/])")),
]


def _valid(year: int, month: int, day: int) -> str | None:
    if not 1900 <= year <= 2100:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def resolve_date(kind: str, groups: dict) -> tuple[str | None, list[str], bool]:
    """Returns (iso_or_None, candidate_isos, valid). A numeric date such as 03/04/2026 with both parts <= 12 is
    ambiguous: iso is None and both readings are returned as candidates. valid=False means impossible (31-Feb)."""
    year = int(groups["y"])
    if kind == "iso":
        iso = _valid(year, int(groups["m"]), int(groups["d"]))
        return iso, [iso] if iso else [], iso is not None
    if kind in ("day_month_name", "month_name_day"):
        month = _MONTHS[groups["mon"][:4].lower() if groups["mon"][:4].lower() == "sept" else groups["mon"][:3].lower()]
        iso = _valid(year, month, int(groups["d"]))
        return iso, [iso] if iso else [], iso is not None
    a, b = int(groups["a"]), int(groups["b"])
    day_first = _valid(year, b, a)  # a = day, b = month
    month_first = _valid(year, a, b)  # a = month, b = day
    candidates = [c for c in dict.fromkeys([day_first, month_first]) if c]
    if not candidates:
        return None, [], False
    if len(candidates) == 1:
        return candidates[0], candidates, True
    return None, candidates, True  # both readings valid -> ambiguous, do not guess


# ---------------------------------------------------------------- frequency / route
_FREQ_RULES: list[tuple[re.Pattern, str, int | None]] = [
    (re.compile(r"\b(?:four\s+times\s+(?:a\s+day|daily)|4\s*x\s*(?:daily|/day)|qid|qds)\b", re.I), "four times daily", 4),
    (re.compile(r"\b(?:three\s+times\s+(?:a\s+day|daily)|3\s*x\s*(?:daily|/day)|tid|tds)\b", re.I), "three times daily", 3),
    (re.compile(r"\b(?:twice\s+(?:a\s+day|daily)|two\s+times\s+(?:a\s+day|daily)|2\s*x\s*(?:daily|/day)|bid|bd|b\.i\.d\.?)(?![A-Za-z])", re.I), "twice daily", 2),
    (re.compile(r"\b(?:once\s+(?:a\s+day|daily)|1\s*x\s*(?:daily|/day)|qd|od|every\s+day|daily)(?![A-Za-z])", re.I), "once daily", 1),
    (re.compile(r"\b(?:at\s+night|nightly|at\s+bedtime|qhs|every\s+night)\b", re.I), "at bedtime", 1),
    (re.compile(r"\b(?:every\s+morning|in\s+the\s+morning|qam)\b", re.I), "every morning", 1),
    (re.compile(r"\b(?:once\s+(?:a\s+week|weekly)|weekly)\b", re.I), "once weekly", None),
]
_EVERY_N_HOURS = re.compile(r"\b(?:every\s+(\d{1,2})\s*(?:hours?|hrs?|h)|q\s?(\d{1,2})\s?h)\b", re.I)
_PRN = re.compile(r"\b(?:as\s+needed|prn|p\.r\.n\.?)(?![A-Za-z])", re.I)

_ROUTE_WORDS = re.compile(r"\b(?:orally|oral|by\s+mouth|intravenous(?:ly)?|intramuscular(?:ly)?|subcutaneous(?:ly)?|subcut|topical(?:ly)?|inhaled|inhalation|sublingual(?:ly)?)\b", re.I)
_ROUTE_ABBR = re.compile(r"\b(?:PO|IV|IM|SC|SQ|SL)\b")
_ROUTE_NAMES = {
    "po": "oral", "iv": "intravenous", "im": "intramuscular", "sc": "subcutaneous", "sq": "subcutaneous", "sl": "sublingual",
    "orally": "oral", "oral": "oral", "bymouth": "oral", "intravenous": "intravenous", "intravenously": "intravenous",
    "intramuscular": "intramuscular", "intramuscularly": "intramuscular", "subcutaneous": "subcutaneous",
    "subcutaneously": "subcutaneous", "subcut": "subcutaneous", "topical": "topical", "topically": "topical",
    "inhaled": "inhaled", "inhalation": "inhaled", "sublingual": "sublingual", "sublingually": "sublingual",
}


def find_frequency(text: str) -> tuple[re.Match, str, int | None, bool] | None:
    """First dose-frequency expression in `text`: (match, normalised, times_per_day, as_needed).
    A PRN marker alone returns ('as needed', None, True)."""
    candidates: list[tuple[int, re.Match, str, int | None, bool]] = []
    for pattern, normalized, times in _FREQ_RULES:
        m = pattern.search(text)
        if m:
            candidates.append((m.start(), m, normalized, times, False))
    m = _EVERY_N_HOURS.search(text)
    if m:
        hours = int(m.group(1) or m.group(2))
        if 1 <= hours <= 72:
            times = 24 // hours if 24 % hours == 0 else None
            candidates.append((m.start(), m, f"every {hours} hours", times, False))
    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, m, normalized, times, _ = candidates[0]
        return m, normalized, times, bool(_PRN.search(text))
    m = _PRN.search(text)
    if m:
        return m, "as needed", None, True
    return None


def find_route(text: str) -> tuple[re.Match, str] | None:
    hits = [m for m in (_ROUTE_WORDS.search(text), _ROUTE_ABBR.search(text)) if m]
    if not hits:
        return None
    m = min(hits, key=lambda h: h.start())
    return m, _ROUTE_NAMES[re.sub(r"\s+", "", m.group(0).lower())]
