#!/usr/bin/env python3
"""Generate the SYNTHETIC sample PDFs in data/sample/.

All content is invented. No real patient information is used, and none must ever be added.

Usage (backend virtualenv active):  python scripts/generate_sample_pdfs.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import pdf_factory as factory  # noqa: E402

OUT = ROOT / "data" / "sample"

DISCHARGE_LINES = [
    "SYNTHETIC DISCHARGE SUMMARY - NOT A REAL PATIENT",
    "Patient: Synthetic Patient A    Admission: 10-Aug-2026    Discharge: 14-Aug-2026",
    "Diagnosis: Type 2 diabetes mellitus (synthetic example).",
    "Medication on discharge: Metformin 500 mg twice daily (synthetic example).",
    "Blood pressure on discharge: 120/80 mmHg.",
]

FILES = {
    "synthetic_lab_report_text.pdf": lambda: factory.text_pdf(
        [factory.LAB_REPORT_LINES, DISCHARGE_LINES], title="Synthetic laboratory report (text)"
    ),
    # 20 pt keeps the widest line inside the page (28 pt clipped it at the right edge)
    "synthetic_lab_report_scanned.pdf": lambda: factory.scanned_pdf([factory.LAB_REPORT_LINES[3:]], fontsize=20),
    "synthetic_mixed_report.pdf": lambda: factory.mixed_pdf(
        factory.LAB_REPORT_LINES, ["Scanned addendum (synthetic)", "Fasting glucose 110 mg/dL"]
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FILES.items():
        data = build()
        (OUT / name).write_bytes(data)
        print(f"wrote data/sample/{name} ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
