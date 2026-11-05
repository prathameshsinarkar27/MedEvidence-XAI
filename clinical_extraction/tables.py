"""Extraction from detected tables: header-mapped column extraction for lab / vital and medication tables, and a
row-text fallback for tables without a recognisable header."""

import re

from clinical_extraction import normalize as nz
from clinical_extraction.extractors import (
    MEDICATION_MATCHER,
    MEASUREMENT_MATCHER,
    build_measurement,
    extract_from_text,
    parse_measurement_tail,
)
from clinical_extraction.models import (
    ASSERT_AFFIRMED,
    ENTITY_MEDICATION,
    FIELD_TABLE_ROW,
    MODALITY_TABLE,
    Evidence,
    TableInput,
)

M_TABLE_LAB = "rule_lab_table_columns_v1"
M_TABLE_MED = "lexicon_medication_table_columns_v1"
M_TABLE_ROW = "rule_table_row_inline_v1"

_HEADERS = {
    "test": r"test|test name|analyte|investigation|parameter|component|lab test|examination",
    "name": r"name",
    "result": r"result|results|value|observed",
    "unit": r"unit|units",
    "reference": r"reference|reference range|ref range|ref\.? range|normal range|normal|range|reference interval|ref",
    "flag": r"flag|flags|abnormal|h/l",
    "date": r"date|collected|collection date|date collected|specimen date",
    "drug": r"drug|medication|medicine|medications|drug name|medicines",
    "dose": r"dose|dosage|strength",
    "frequency": r"frequency|freq|sig|directions|schedule|how often",
    "route": r"route",
}
_HEADER_RES = {role: re.compile(rf"^(?:{pat})$") for role, pat in _HEADERS.items()}


def _clean_header(text: str | None) -> str:
    text = re.sub(r"\([^)]*\)", "", (text or "").lower()).strip().rstrip(":").strip()
    return re.sub(r"\s+", " ", text)


def find_header(rows: list[list[str | None]]) -> tuple[int, dict[str, int]] | None:
    """First row (within the first 3) in which at least two cells match known header names."""
    for r, row in enumerate(rows[:3]):
        roles: dict[str, int] = {}
        for c, cell in enumerate(row):
            header = _clean_header(cell)
            for role, regex in _HEADER_RES.items():
                if role not in roles and regex.match(header):
                    roles[role] = c
                    break
        if len(roles) >= 2:
            return r, roles
    return None


def _cell(row: list[str | None], roles: dict[str, int], role: str) -> tuple[str, int] | None:
    c = roles.get(role)
    if c is None or c >= len(row) or row[c] is None or not row[c].strip():
        return None
    return row[c].strip(), c


def _row_source(row: list[str | None]) -> str:
    return " | ".join(c.strip() for c in row if c and c.strip())


def _lab_row(table: TableInput, r: int, roles: dict[str, int], name_role: str) -> Evidence | None:
    row = table.rows[r]
    name = _cell(row, roles, name_role)
    result = _cell(row, roles, "result")
    if not name or not result:
        return None
    entry = MEASUREMENT_MATCHER.lookup(re.sub(r"\s*[:*]+$", "", name[0]))
    if entry is None:
        found = next(iter(MEASUREMENT_MATCHER.find(name[0])), None)
        if found and found[0].start() <= 2 and (found[0].end() - found[0].start()) >= 0.5 * len(name[0]):
            entry = found[1]
    if entry is None:
        return None
    cells = [name[1], result[1]]
    value_cell = result[0]
    unit_cell = _cell(row, roles, "unit")
    tail = value_cell + (" " + unit_cell[0] if unit_cell else "")
    parsed = parse_measurement_tail(entry, tail)
    if parsed is None or parsed["consumed"] < len(value_cell):
        # the unit column text did not parse as a unit for this test: try the value cell alone
        parsed = parse_measurement_tail(entry, value_cell)
        if parsed is None:
            return None
    elif unit_cell:
        cells.append(unit_cell[1])
    ref_cell = _cell(row, roles, "reference")
    if ref_cell:
        cells.append(ref_cell[1])
        rp = parse_measurement_tail(entry, "0 " + ref_cell[0])  # reuse the range parser on "<value> <range>"
        if rp and parsed["reference_text"] is None:
            for k in ("reference_text", "reference_low", "reference_high"):
                parsed[k] = rp[k]
        if parsed["reference_text"] is None:
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)", ref_cell[0])
            if m and float(m[1]) < float(m[2]):
                parsed.update(reference_text=ref_cell[0], reference_low=float(m[1]), reference_high=float(m[2]))
    flag_cell = _cell(row, roles, "flag")
    if flag_cell:
        cells.append(flag_cell[1])
        fm = re.fullmatch(r"(?i)(HH|LL|H|L|High|Low|Critical)", flag_cell[0].strip("() *"))
        if fm:
            parsed["flag_text"] = fm.group(1)
    ev = build_measurement(entry, parsed)
    date_cell = _cell(row, roles, "date")
    if date_cell:
        cells.append(date_cell[1])
        for d in extract_from_text(date_cell[0]):
            if d.entity_type == "date" and d.date_iso:
                ev.date_text, ev.date_iso = d.date_text, d.date_iso
                ev.attributes["date_from"] = "table_date_column"
                break
    ev.mention_text = name[0]
    ev.extraction_method = M_TABLE_LAB
    ev.cell_positions = sorted({(r, c) for c in cells})
    return ev


def _med_row(table: TableInput, r: int, roles: dict[str, int], name_role: str) -> Evidence | None:
    row = table.rows[r]
    name = _cell(row, roles, name_role)
    if not name:
        return None
    found = next(iter(MEDICATION_MATCHER.find(name[0])), None)
    if found is None:
        return None
    entry = found[1]
    cells = [name[1]]
    ev = Evidence(
        entity_type=ENTITY_MEDICATION, entity_name=entry.name, mention_text=name[0], source_text="",
        modality=MODALITY_TABLE, extraction_method=M_TABLE_MED, assertion=ASSERT_AFFIRMED,
        attributes={"matched_name": found[0].group(0)},
    )
    dose = _cell(row, roles, "dose")
    if dose:
        cells.append(dose[1])
        dm = re.search(rf"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{nz.DOSE_UNIT_PATTERN})(?![A-Za-z0-9])", dose[0], re.I)
        if dm:
            ev.value_text, ev.value_numeric = dm.group(0), float(dm["num"])
            ev.unit_text, ev.unit_normalized = dm["unit"], nz.normalize_unit(dm["unit"])
    freq = _cell(row, roles, "frequency")
    if freq:
        cells.append(freq[1])
        f = nz.find_frequency(freq[0])
        if f:
            ev.attributes.update(frequency_text=f[0].group(0), frequency_normalized=f[1], times_per_day=f[2], as_needed=f[3])
    route = _cell(row, roles, "route")
    if route:
        cells.append(route[1])
        rt = nz.find_route(route[0])
        if rt:
            ev.attributes.update(route=rt[1], route_text=rt[0].group(0))
    ev.cell_positions = sorted({(r, c) for c in cells})
    return ev


def extract_from_table(table: TableInput) -> tuple[list[Evidence], dict]:
    """Returns (evidence, stats). Rows that cannot be read are counted, never guessed."""
    stats = {"rows_seen": 0, "rows_extracted": 0, "rows_unrecognised": 0, "header_found": False}
    rows = table.rows
    header = find_header(rows)
    results: list[Evidence] = []
    if header:
        stats["header_found"] = True
        h, roles = header
        has_result = "result" in roles and ("test" in roles or "name" in roles)
        has_med = "drug" in roles or ("name" in roles and ("dose" in roles or "frequency" in roles))
        for r in range(h + 1, len(rows)):
            if not any(c and c.strip() for c in rows[r]):
                continue
            stats["rows_seen"] += 1
            ev = None
            if has_result:
                ev = _lab_row(table, r, roles, "test" if "test" in roles else "name")
            elif has_med:
                ev = _med_row(table, r, roles, "drug" if "drug" in roles else "name")
            if ev is None:
                stats["rows_unrecognised"] += 1
                continue
            ev.source_text = _row_source(rows[r])
            ev.source_field, ev.modality = FIELD_TABLE_ROW, MODALITY_TABLE
            ev.table_ref, ev.row_index = table.ref, r
            results.append(ev)
            stats["rows_extracted"] += 1
        if has_result or has_med:
            return results, stats
        results = []
        stats.update(rows_seen=0, rows_extracted=0, rows_unrecognised=0)

    # fallback: run the inline text rules on every row's text
    for r, row in enumerate(rows):
        cells = [c.strip() for c in row if c and c.strip()]
        if not cells:
            continue
        stats["rows_seen"] += 1
        row_text = " | ".join(cells)
        found = [e for e in extract_from_text(row_text) if e.entity_type != "date"]
        if not found:
            stats["rows_unrecognised"] += 1
            continue
        stats["rows_extracted"] += 1
        for ev in found:
            ev.source_text = " | ".join(cells)
            ev.source_field, ev.modality = FIELD_TABLE_ROW, MODALITY_TABLE
            ev.char_start = ev.char_end = ev.source_start = ev.source_end = None
            ev.extraction_method = M_TABLE_ROW
            ev.table_ref, ev.row_index = table.ref, r
            ev.cell_positions = [(r, c) for c, cell in enumerate(row) if cell and cell.strip()]
            results.append(ev)
    return results, stats
