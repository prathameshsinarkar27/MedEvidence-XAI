"""Unit tests for the clinical extraction library. All text is synthetic."""

import pytest

from clinical_extraction import TableInput, extract_table_evidence, extract_text_evidence, lexicon_sizes
from clinical_extraction import normalize as nz
from clinical_extraction.context import sentence_spans


def ev(text, **kw):
    return extract_text_evidence(text, **kw)


def one(text, entity_type=None, name=None):
    items = [e for e in ev(text) if (entity_type is None or e.entity_type == entity_type) and (name is None or e.entity_name == name)]
    assert len(items) == 1, items
    return items[0]


# ------------------------------------------------------------ traceability invariants
SAMPLE = (
    "SYNTHETIC REPORT\nReport date: 12-Aug-2026\nHemoglobin A1c       7.8        %        4.0 - 5.6\n"
    "Patient denies chest pain or fever. Metformin 500 mg twice daily PO. BP 140/90 mmHg.\n"
    "HbA1c was 7.8% on 2026-08-12; history of type 2 diabetes mellitus.\n"
)


def test_every_mention_is_a_verbatim_span_of_the_source_and_inside_its_sentence():
    items = ev(SAMPLE)
    assert len(items) >= 8
    for e in items:
        assert SAMPLE[e.char_start:e.char_end] == e.mention_text
        assert SAMPLE[e.source_start:e.source_end] == e.source_text
        assert e.source_start <= e.char_start and e.char_end <= e.source_end
        assert e.mention_text in e.source_text
        assert 0.05 <= e.confidence <= 0.99 and "base" in e.confidence_factors


def test_nothing_is_invented_from_unknown_text():
    assert ev("The quick brown fox jumps over 12 lazy dogs. Widget count 55 units.") == []
    assert ev("") == [] and ev("   \n ") == []


def test_unknown_test_names_are_not_extracted():
    assert ev("Zorbitol 55 mg/dL") == []


# ------------------------------------------------------------ measurements
def test_lab_inline_with_unit_reference_and_computed_flag():
    e = one("Hemoglobin A1c       7.8        %        4.0 - 5.6", "lab_result")
    assert (e.entity_name, e.value_text, e.value_numeric, e.unit_text, e.unit_normalized) == ("Hemoglobin A1c", "7.8", 7.8, "%", "%")
    assert (e.reference_text, e.reference_low, e.reference_high) == ("4.0 - 5.6", 4.0, 5.6)
    assert (e.abnormal_flag, e.flag_source) == ("high", "printed_reference_range")


def test_printed_flag_wins_and_no_flag_without_printed_evidence():
    assert one("Potassium 3.1 mmol/L L", "lab_result").abnormal_flag == "low"
    e = one("Potassium 3.1 mmol/L", "lab_result")
    assert e.abnormal_flag is None and e.flag_source is None  # never judged from internal "normal" ranges


def test_unit_spelling_is_normalised_but_value_is_never_converted():
    e = one("Fasting glucose 110 mg/dl", "lab_result")
    assert (e.unit_text, e.unit_normalized, e.value_numeric) == ("mg/dl", "mg/dL", 110.0)
    e = one("Creatinine 88 umol/L", "lab_result")
    assert e.unit_normalized == "µmol/L" and e.value_numeric == 88.0


def test_synonyms_map_to_one_canonical_name():
    for text in ("HbA1c 7.8 %", "Glycated hemoglobin 7.8 %", "hemoglobin a1c: 7.8%"):
        assert one(text, "lab_result").entity_name == "Hemoglobin A1c"
    assert one("Hemoglobin 13.5 g/dL", "lab_result").entity_name == "Hemoglobin"


def test_free_text_gap_words_and_comparator():
    e = one("The HbA1c was 7.8% on that visit.", "lab_result")
    assert e.value_numeric == 7.8
    e = one("Troponin I <0.01 ng/mL", "lab_result")
    assert e.value_comparator == "<" and e.value_numeric == 0.01


def test_number_followed_by_unrelated_word_or_wrong_unit_is_not_a_result():
    assert ev("Sodium 2 grams restriction advised") == []
    assert [e for e in ev("Calcium 500 mg daily with food") if e.entity_type == "lab_result"] == []


def test_result_without_unit_is_kept_with_lower_confidence():
    with_unit = one("Potassium 4.2 mmol/L", "lab_result")
    without = one("Potassium 4.2", "lab_result")
    assert without.unit_normalized is None and without.confidence < with_unit.confidence
    assert "no_unit" in without.confidence_factors


def test_implausible_value_is_kept_but_flagged_and_penalised():
    e = one("Potassium 42 mmol/L", "lab_result")
    assert e.attributes["implausible_value"] is True and e.value_text == "42"
    assert e.confidence < one("Potassium 4.2 mmol/L", "lab_result").confidence


def test_dates_after_a_value_are_not_mistaken_for_a_reference_range():
    e = one("Glucose 110 mg/dL 2026-08-12", "lab_result")
    assert e.reference_text is None
    e = one("Glucose 110 mg/dL 12-08-2026", "lab_result")
    assert e.reference_text is None


def test_blood_pressure_and_other_vitals():
    bp = one("BP 140/90 mmHg", "vital_sign")
    assert (bp.value_text, bp.attributes["systolic"], bp.attributes["diastolic"], bp.unit_normalized) == ("140/90", 140, 90, "mmHg")
    assert ev("BP 90/140") == []  # systolic must exceed diastolic
    assert one("Heart rate 78 bpm", "vital_sign").value_numeric == 78.0
    t = one("Temperature 38.2 °C", "vital_sign")
    assert t.unit_normalized == "°C"
    assert one("Temp 98.6 F", "vital_sign").unit_normalized == "°F"
    assert one("SpO2 97%", "vital_sign").value_numeric == 97.0
    assert ev("Weight 70") == []  # weight needs a unit


def test_decimal_comma_and_thousands_separator():
    assert nz.parse_number("7,8") == 7.8
    assert nz.parse_number("1,200") == 1200.0
    assert nz.parse_number("abc") is None


# ------------------------------------------------------------ assertion
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Patient denies chest pain.", "negated"),
        ("No fever, cough or headache.", "negated"),
        ("No fever but has cough.", "affirmed"),  # scope ends at "but"
        ("Patient has chest pain.", "affirmed"),
        ("Possible pneumonia on imaging.", "uncertain"),
        ("Pneumonia is suspected.", "uncertain"),
        ("Mother had type 2 diabetes mellitus.", "family_history"),
        ("Family history of hypertension.", "family_history"),
        ("Cough was ruled out.", "negated"),
    ],
)
def test_assertion(text, expected):
    items = [e for e in ev(text) if e.entity_type in ("condition", "symptom")]
    assert items and items[-1].assertion == expected, (text, [(e.entity_name, e.assertion) for e in items])


def test_historical_temporality_is_recorded_without_changing_assertion():
    e = one("History of asthma.", "condition")
    assert e.assertion == "affirmed" and e.attributes["temporality"] == "historical"


def test_longest_term_wins_and_no_overlap():
    names = [e.entity_name for e in ev("Type 2 diabetes mellitus and pulmonary hypertension.")]
    assert names == ["Type 2 diabetes mellitus", "Pulmonary hypertension"]
    assert [e.entity_name for e in ev("Diabetes insipidus.")] == ["Diabetes insipidus"]


def test_abbreviations_are_case_sensitive():
    assert one("Known CKD.", "condition").entity_name == "Chronic kidney disease"
    assert ev("The ckd word in lower case.") == []
    assert ev("Result is N/A today. na") == []


# ------------------------------------------------------------ medications
def test_medication_with_dose_frequency_route():
    e = one("Metformin 500 mg twice daily PO", "medication")
    assert e.entity_name == "Metformin" and (e.value_numeric, e.unit_normalized) == (500.0, "mg")
    assert e.attributes["frequency_normalized"] == "twice daily" and e.attributes["times_per_day"] == 2
    assert e.attributes["route"] == "oral" and e.assertion == "affirmed"


def test_medication_brand_to_generic_and_dose_before_name():
    assert one("Takes Lipitor 20 mg at night", "medication").entity_name == "Atorvastatin"
    e = one("Started 5 mg amlodipine once daily", "medication")
    assert e.entity_name == "Amlodipine" and e.value_numeric == 5.0


def test_medication_context_assertions():
    assert one("Allergic to penicillin.", "medication").assertion == "allergy"
    assert one("Aspirin was discontinued last month.", "medication").assertion == "discontinued"
    assert one("Patient is not taking warfarin.", "medication").assertion == "negated"
    assert one("Consider starting metformin.", "medication").assertion == "planned"


def test_prn_and_every_n_hours():
    e = one("Paracetamol 500 mg every 8 hours as needed", "medication")
    assert e.attributes["times_per_day"] == 3 and e.attributes["as_needed"] is True


def test_two_medications_do_not_borrow_each_others_dose():
    items = [e for e in ev("Metformin and amlodipine 5 mg daily.") if e.entity_type == "medication"]
    by = {e.entity_name: e for e in items}
    assert by["Metformin"].value_numeric is None and by["Amlodipine"].value_numeric == 5.0


# ------------------------------------------------------------ dates
def test_date_formats_normalise_and_keep_original():
    for text, iso in [("2026-08-12", "2026-08-12"), ("12-Aug-2026", "2026-08-12"), ("Aug 12, 2026", "2026-08-12"),
                      ("12 August 2026", "2026-08-12"), ("25/12/2026", "2026-12-25"), ("12/25/2026", "2026-12-25")]:
        e = one(f"Seen on {text}.", "date")
        assert e.date_iso == iso and e.date_text == text


def test_ambiguous_and_impossible_dates_are_not_guessed():
    e = one("Seen 03/04/2026.", "date")
    assert e.date_iso is None and e.attributes["ambiguous"] and set(e.attributes["candidates"]) == {"2026-03-04", "2026-04-03"}
    assert e.confidence < 0.6
    assert ev("Seen 31-Feb-2026.") == []
    assert ev("Seen 2026-13-45.") == []


def test_date_role_and_event_date_only_from_same_sentence():
    e = one("Report date: 12-Aug-2026", "date")
    assert e.entity_name == "report_date"
    lab = one("HbA1c 7.8 % on 12-Aug-2026", "lab_result")
    assert lab.date_iso == "2026-08-12"
    items = ev("Report date: 12-Aug-2026\nHbA1c 7.8 %")
    assert [x for x in items if x.entity_type == "lab_result"][0].date_iso is None  # not inferred from another line


# ------------------------------------------------------------ OCR confidence
def test_ocr_text_lowers_confidence_by_a_documented_factor():
    clean = one("HbA1c 7.8 %", "lab_result").confidence
    ocr = extract_text_evidence("HbA1c 7.8 %", modality="ocr", ocr_confidence=50)[0]
    assert ocr.modality == "ocr" and ocr.confidence < clean
    assert ocr.confidence_factors["ocr_text_reliability_multiplier"] == 0.8
    unknown = extract_text_evidence("HbA1c 7.8 %", modality="ocr", ocr_confidence=None)[0]
    assert unknown.confidence_factors["ocr_text_reliability_multiplier"] == 0.7


# ------------------------------------------------------------ sentences
def test_sentence_spans_keep_wrapped_lines_together_and_split_records():
    text = "Patient has a history of\nhypertension and diabetes.\nHbA1c 7.8 %\nSodium 140 mmol/L"
    pieces = [text[s:e] for s, e in sentence_spans(text)]
    assert pieces == ["Patient has a history of\nhypertension and diabetes.", "HbA1c 7.8 %", "Sodium 140 mmol/L"]


# ------------------------------------------------------------ tables
LAB_ROWS = [["Test", "Result", "Unit", "Reference"], ["Hemoglobin A1c", "7.8", "%", "4.0 - 5.6"],
            ["Fasting glucose", "110", "mg/dL", "70 - 99"], ["Sodium", "140", "mmol/L", "135 - 145"], ["Mystery", "5", "x", ""]]


def test_lab_table_with_header():
    items, stats = extract_table_evidence(TableInput("T1", LAB_ROWS))
    assert [e.entity_name for e in items] == ["Hemoglobin A1c", "Fasting glucose", "Sodium"]
    assert [e.abnormal_flag for e in items] == ["high", "high", "normal"]
    first = items[0]
    assert (first.modality, first.table_ref, first.row_index) == ("table", "T1", 1)
    assert first.cell_positions == [(1, 0), (1, 1), (1, 2), (1, 3)]
    assert first.source_text == "Hemoglobin A1c | 7.8 | % | 4.0 - 5.6" and first.char_start is None
    assert stats["rows_unrecognised"] == 1 and stats["header_found"]  # "Mystery" skipped, not guessed
    assert first.confidence > one("Hemoglobin A1c 7.8 %", "lab_result").confidence


def test_medication_table_with_header():
    rows = [["Drug", "Dose", "Frequency"], ["Metformin", "500 mg", "twice daily"], ["Amlodipine", "5 mg", "once daily"]]
    items, _ = extract_table_evidence(TableInput("T2", rows))
    assert [(e.entity_name, e.value_numeric, e.attributes["times_per_day"]) for e in items] == [("Metformin", 500.0, 2), ("Amlodipine", 5.0, 1)]


def test_headerless_table_falls_back_to_row_text_and_keeps_cells():
    items, stats = extract_table_evidence(TableInput("T3", [["Hemoglobin A1c", "7.8", "%", "4.0 - 5.6"], ["blah", "blah"]]))
    assert len(items) == 1 and items[0].extraction_method == "rule_table_row_inline_v1"
    assert items[0].value_numeric == 7.8 and items[0].cell_positions == [(0, 0), (0, 1), (0, 2), (0, 3)]
    assert stats["header_found"] is False


def test_qualitative_or_empty_table_rows_are_skipped():
    rows = [["Test", "Result"], ["Sodium", "Positive"], ["Potassium", ""], [None, None]]
    items, stats = extract_table_evidence(TableInput("T4", rows))
    assert items == [] and stats["rows_unrecognised"] == 2


def test_lexicon_sizes():
    sizes = lexicon_sizes()
    assert sizes["lab_tests"] >= 30 and sizes["medications"] >= 50


# ------------------------------------------------------------ one-cell-per-line layout (typical PDF text layer of a table)
VERTICAL = ("Test\nResult\nUnit\nReference\nHemoglobin A1c\n7.8\n%\n4.0 - 5.6\nFasting glucose\n110\nmg/dL\n70 - 99\n"
            "Sodium\n140\nmmol/L\n135 - 145\nDrug\nDose\nFrequency\nMetformin\n500 mg\ntwice daily\nAmlodipine\n5 mg\nonce daily\n")


def test_cell_per_line_layout_is_read_and_stays_traceable():
    items = ev(VERTICAL)
    labs = [e for e in items if e.entity_type == "lab_result"]
    assert [(e.entity_name, e.value_numeric, e.unit_normalized, e.reference_text) for e in labs] == [
        ("Hemoglobin A1c", 7.8, "%", "4.0 - 5.6"), ("Fasting glucose", 110.0, "mg/dL", "70 - 99"), ("Sodium", 140.0, "mmol/L", "135 - 145")]
    meds = [e for e in items if e.entity_type == "medication"]
    assert [(e.entity_name, e.value_numeric, e.attributes["times_per_day"]) for e in meds] == [("Metformin", 500.0, 2), ("Amlodipine", 5.0, 1)]
    for e in items:
        assert VERTICAL[e.char_start:e.char_end] == e.mention_text and e.mention_text in e.source_text
        assert VERTICAL[e.source_start:e.source_end] == e.source_text


def test_a_date_on_the_next_line_is_not_a_lab_value():
    assert [e for e in ev("Glucose\n2026-08-12\n") if e.entity_type == "lab_result"] == []
    assert [e for e in ev("Glucose\n12:30\n") if e.entity_type == "lab_result"] == []


def test_date_role_is_found_across_a_line_break():
    assert one("Report date:\n12-Aug-2026", "date").entity_name == "report_date"
