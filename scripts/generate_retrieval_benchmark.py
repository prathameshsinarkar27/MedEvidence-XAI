#!/usr/bin/env python3
"""Generate the SYNTHETIC retrieval-benchmark documents in data/benchmark/retrieval/documents/.

All patients, values and dates are invented. No real patient information is used, and none must ever be added.
The queries and relevance judgments are written by hand in data/benchmark/retrieval/queries.json from the text
below (not from system output).

Usage (backend virtualenv active):  python scripts/generate_retrieval_benchmark.py
"""

import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import pdf_factory as factory  # noqa: E402

OUT = ROOT / "data" / "benchmark" / "retrieval" / "documents"
TABLE_COLS = [110, 60, 70, 90, 90]
HEADER = ["Test", "Result", "Unit", "Reference", "Date"]


def build(pages) -> bytes:
    """pages: list of (lines, table_rows|None). Text at 9 pt; ruled table below the text."""
    doc = pymupdf.open()
    for lines, table in pages:
        page = doc.new_page()
        factory._write_lines(page, lines, 9, top=80, step=15)
        if table:
            top = 80 + 15 * len(lines) + 25
            factory.draw_ruled_table(page, [HEADER, *table], y0=top, col_widths=TABLE_COLS)
    return doc.tobytes(deflate=True, garbage=3)


A = build([
    (["SYNTHETIC VISIT NOTE A - NOT A REAL PATIENT (Patient Alpha)",
      "Visit date: 03-May-2026",
      "Patient reports polydipsia and fatigue. Denies chest pain.",
      "History of type 2 diabetes mellitus.",
      "Metformin 500 mg twice daily PO.",
      "BP 150/95 mmHg.",
      "HbA1c was 8.2 % on 03-May-2026.",
      "Potassium 4.4 mmol/L on 03-May-2026."], None),
    (["SYNTHETIC LABORATORY RESULTS A - NOT A REAL PATIENT (Patient Alpha)"],
     [["Fasting glucose", "142", "mg/dL", "70 - 99", "03-May-2026"],
      ["Sodium", "139", "mmol/L", "135 - 145", "03-May-2026"],
      ["Creatinine", "1.0", "mg/dL", "0.6 - 1.2", "03-May-2026"]]),
])
B = build([
    (["SYNTHETIC FOLLOW-UP NOTE B - NOT A REAL PATIENT (Patient Alpha)",
      "Visit date: 12-Aug-2026",
      "Patient denies fatigue. Reports cough and headache.",
      "Metformin increased to 1000 mg twice daily PO.",
      "Started atorvastatin 20 mg once daily.",
      "BP 120/80 mmHg.",
      "HbA1c was 7.8 % on 12-Aug-2026.",
      "Potassium 4.1 mmol/L on 12-Aug-2026."],
     [["Fasting glucose", "118", "mg/dL", "70 - 99", "12-Aug-2026"],
      ["Sodium", "141", "mmol/L", "135 - 145", "12-Aug-2026"],
      ["LDL cholesterol", "131", "mg/dL", "0 - 100", "12-Aug-2026"],
      ["Triglycerides", "160", "mg/dL", "0 - 150", "12-Aug-2026"]]),
])
C = build([
    (["SYNTHETIC CARDIOLOGY NOTE C - NOT A REAL PATIENT (Patient Beta)",
      "Presents with palpitations and shortness of breath. Chest pain on exertion.",
      "History of hypertension and atrial fibrillation.",
      "Father had myocardial infarction. Allergic to penicillin.",
      "Amlodipine 5 mg once daily. Warfarin 5 mg once daily. Metoprolol 50 mg twice daily.",
      "BP 160/100 mmHg on 21-Jun-2026.",
      "Heart rate 110 bpm.",
      "INR 2.4. Troponin I 12 ng/L on 21-Jun-2026."], None),
])
D = build([
    (["SYNTHETIC DISCHARGE SUMMARY D - NOT A REAL PATIENT (Patient Gamma)",
      "Admitted with pneumonia and fever. Discharged on 02-Sep-2026.",
      "Treated with amoxicillin 500 mg three times daily. Paracetamol 650 mg as needed.",
      "WBC 14.2 10^9/L on 30-Aug-2026.",
      "CRP 85 mg/L on 30-Aug-2026.",
      "Temperature 38.6 °C on 30-Aug-2026.",
      "SpO2 93 % on 30-Aug-2026.",
      "SpO2 97 % on 02-Sep-2026.",
      "Hemoglobin 11.2 g/dL. Anemia noted."], None),
])
E = build([
    (["SYNTHETIC LABORATORY RESULTS E - NOT A REAL PATIENT (Patient Alpha)"],
     [["Hemoglobin A1c", "7.5", "%", "4.0 - 5.6", "15-Sep-2026"],
      ["Fasting glucose", "112", "mg/dL", "70 - 99", "15-Sep-2026"],
      ["Potassium", "4.3", "mmol/L", "3.5 - 5.1", "15-Sep-2026"],
      ["Sodium", "140", "mmol/L", "135 - 145", "15-Sep-2026"],
      ["Creatinine", "1.1", "mg/dL", "0.6 - 1.2", "15-Sep-2026"],
      ["Total cholesterol", "190", "mg/dL", "0 - 200", "15-Sep-2026"]]),
])
F = factory.scanned_pdf([[
    "SYNTHETIC SCANNED NOTE F (Patient Delta)",
    "Reports fatigue and weight loss.",
    "TSH 6.8 mIU/L on 10-Oct-2026.",
    "Levothyroxine 50 mcg once daily.",
]], fontsize=20)

FILES = {
    "bench_a_visit_may.pdf": A, "bench_b_followup_aug.pdf": B, "bench_c_cardiology.pdf": C,
    "bench_d_discharge.pdf": D, "bench_e_labs_sep.pdf": E, "bench_f_scanned.pdf": F,
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (OUT / name).write_bytes(content)
        print(f"wrote {name} ({len(content)} bytes)")
