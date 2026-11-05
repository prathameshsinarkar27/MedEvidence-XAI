"""Small built-in vocabularies. Deliberately limited and transparent: a term that is not listed here is never
extracted (the extractor does not guess). See docs/clinical-information-extraction.md for how to extend it.

Abbreviations (all capitals, up to 5 letters) are matched case-sensitively; every other term ignores case.
"""

from dataclasses import dataclass, field

KIND_LAB = "lab"
KIND_VITAL = "vital"
KIND_MEDICATION = "medication"
KIND_CONDITION = "condition"
KIND_SYMPTOM = "symptom"


@dataclass(frozen=True)
class LexEntry:
    name: str  # canonical name
    kind: str
    synonyms: tuple[str, ...] = ()
    units: tuple[str, ...] = ()  # canonical units a result may carry; empty = unit-less
    # Crude physiological plausibility range per canonical unit ("*" = any/unknown unit). Used only to LOWER
    # confidence and flag typos; it never changes or rejects the value as written.
    plausible: dict = field(default_factory=dict, hash=False, compare=False)
    unit_required: bool = False

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.name, *self.synonyms)


def _lab(name, synonyms, units, plausible, kind=KIND_LAB, unit_required=False):
    return LexEntry(name, kind, tuple(synonyms), tuple(units), dict(plausible), unit_required)


_GLUCOSE_P = {"mg/dL": (20, 1000), "mmol/L": (1, 55), "*": (1, 1000)}
_LIPID_P = {"mg/dL": (5, 1500), "mmol/L": (0.1, 40), "*": (0.1, 1500)}
_ELECTROLYTE_P = lambda lo, hi: {"*": (lo, hi)}  # noqa: E731

LAB_ENTRIES: tuple[LexEntry, ...] = (
    _lab("Hemoglobin A1c", ["HbA1c", "Haemoglobin A1c", "Glycated hemoglobin", "Glycosylated hemoglobin", "A1c", "HgbA1c"],
         ["%", "mmol/mol"], {"%": (2, 20), "mmol/mol": (10, 200), "*": (2, 250)}),
    _lab("Fasting glucose", ["Fasting blood glucose", "Fasting blood sugar", "FBG", "FBS"], ["mg/dL", "mmol/L"], _GLUCOSE_P),
    _lab("Glucose", ["Blood glucose", "Random glucose", "Random blood glucose", "Blood sugar"], ["mg/dL", "mmol/L"], _GLUCOSE_P),
    _lab("Sodium", ["Na"], ["mmol/L", "mEq/L"], _ELECTROLYTE_P(90, 190)),
    _lab("Potassium", [], ["mmol/L", "mEq/L"], _ELECTROLYTE_P(1.5, 10)),
    _lab("Chloride", [], ["mmol/L", "mEq/L"], _ELECTROLYTE_P(60, 140)),
    _lab("Bicarbonate", ["HCO3"], ["mmol/L", "mEq/L"], _ELECTROLYTE_P(5, 50)),
    _lab("Blood urea nitrogen", ["BUN"], ["mg/dL"], {"*": (1, 300)}),
    _lab("Urea", [], ["mmol/L", "mg/dL"], {"*": (0.5, 300)}),
    _lab("Creatinine", ["Serum creatinine"], ["mg/dL", "µmol/L"], {"mg/dL": (0.1, 25), "µmol/L": (10, 2200), "*": (0.1, 2200)}),
    _lab("eGFR", ["Estimated GFR"], ["mL/min/1.73 m²"], {"*": (1, 200)}),
    _lab("Calcium", [], ["mg/dL", "mmol/L"], {"mg/dL": (3, 20), "mmol/L": (0.7, 5), "*": (0.7, 20)}),
    _lab("Magnesium", [], ["mg/dL", "mmol/L", "mEq/L"], {"*": (0.2, 10)}),
    _lab("Phosphate", ["Phosphorus"], ["mg/dL", "mmol/L"], {"*": (0.2, 20)}),
    _lab("Hemoglobin", ["Haemoglobin", "Hgb", "Hb"], ["g/dL", "g/L"], {"g/dL": (2, 25), "g/L": (20, 250), "*": (2, 250)}),
    _lab("Hematocrit", ["Haematocrit", "Hct"], ["%"], {"*": (5, 70)}),
    _lab("White blood cell count", ["White blood cells", "WBC", "Leukocytes"], ["10^9/L", "10^3/µL", "/µL"], {"*": (0.1, 500000)}),
    _lab("Red blood cell count", ["Red blood cells", "RBC"], ["10^12/L", "10^6/µL"], {"*": (0.5, 10)}),
    _lab("Platelet count", ["Platelets", "PLT"], ["10^9/L", "10^3/µL", "/µL"], {"*": (1, 2000000)}),
    _lab("Mean corpuscular volume", ["MCV"], ["fL"], {"*": (40, 150)}),
    _lab("Alanine aminotransferase", ["ALT", "SGPT"], ["U/L", "IU/L"], {"*": (1, 5000)}),
    _lab("Aspartate aminotransferase", ["AST", "SGOT"], ["U/L", "IU/L"], {"*": (1, 5000)}),
    _lab("Alkaline phosphatase", ["ALP"], ["U/L", "IU/L"], {"*": (5, 3000)}),
    _lab("Total bilirubin", ["Bilirubin"], ["mg/dL", "µmol/L"], {"*": (0.05, 600)}),
    _lab("Albumin", [], ["g/dL", "g/L"], {"g/dL": (0.5, 7), "g/L": (5, 70), "*": (0.5, 70)}),
    _lab("Total cholesterol", ["Cholesterol"], ["mg/dL", "mmol/L"], _LIPID_P),
    _lab("LDL cholesterol", ["LDL-C", "LDL"], ["mg/dL", "mmol/L"], _LIPID_P),
    _lab("HDL cholesterol", ["HDL-C", "HDL"], ["mg/dL", "mmol/L"], _LIPID_P),
    _lab("Triglycerides", ["TG"], ["mg/dL", "mmol/L"], _LIPID_P),
    _lab("Thyroid stimulating hormone", ["TSH"], ["mIU/L", "µIU/mL"], {"*": (0.001, 500)}),
    _lab("Free T4", ["FT4"], ["ng/dL", "pmol/L"], {"*": (0.1, 100)}),
    _lab("C-reactive protein", ["CRP"], ["mg/L", "mg/dL"], {"*": (0.01, 1000)}),
    _lab("Erythrocyte sedimentation rate", ["ESR"], ["mm/h"], {"*": (0, 200)}),
    _lab("INR", [], [], {"*": (0.5, 15)}),
    _lab("Troponin I", ["hs-cTnI"], ["ng/L", "ng/mL"], {"*": (0, 100000)}),
    _lab("Ferritin", [], ["ng/mL", "µg/L"], {"*": (1, 10000)}),
    _lab("Vitamin D", ["25-hydroxyvitamin D", "25-OH vitamin D"], ["ng/mL", "nmol/L"], {"*": (1, 500)}),
    _lab("Uric acid", [], ["mg/dL", "µmol/L"], {"*": (0.5, 1500)}),
)

VITAL_ENTRIES: tuple[LexEntry, ...] = (
    _lab("Blood pressure", ["BP"], ["mmHg"], {"*": (20, 300)}, KIND_VITAL),  # handled specially (systolic/diastolic)
    _lab("Heart rate", ["Pulse", "HR", "Pulse rate"], ["bpm", "/min"], {"*": (20, 300)}, KIND_VITAL),
    _lab("Respiratory rate", ["RR", "Resp rate"], ["breaths/min", "/min"], {"*": (4, 80)}, KIND_VITAL),
    _lab("Temperature", ["Temp"], ["°C", "°F"], {"°C": (25, 45), "°F": (77, 113), "*": (25, 113)}, KIND_VITAL, True),
    _lab("Oxygen saturation", ["SpO2", "O2 saturation", "O2 sat"], ["%"], {"*": (50, 100)}, KIND_VITAL),
    _lab("Weight", ["Body weight"], ["kg", "lb"], {"kg": (0.3, 500), "lb": (1, 1100), "*": (0.3, 1100)}, KIND_VITAL, True),
    _lab("Height", ["Body height"], ["cm"], {"*": (30, 260)}, KIND_VITAL, True),
    _lab("Body mass index", ["BMI"], ["kg/m²"], {"*": (8, 100)}, KIND_VITAL),
)

MEASUREMENT_ENTRIES = LAB_ENTRIES + VITAL_ENTRIES


def _simple(kind, rows):
    return tuple(LexEntry(name, kind, tuple(syn)) for name, syn in rows)


MEDICATION_ENTRIES: tuple[LexEntry, ...] = _simple(KIND_MEDICATION, [
    ("Metformin", ["Glucophage"]), ("Glimepiride", []), ("Gliclazide", []), ("Insulin glargine", ["Lantus"]),
    ("Insulin", []), ("Sitagliptin", []), ("Empagliflozin", []), ("Dapagliflozin", []), ("Liraglutide", []),
    ("Semaglutide", []), ("Amlodipine", ["Norvasc"]), ("Lisinopril", ["Zestril"]), ("Enalapril", []),
    ("Ramipril", []), ("Losartan", []), ("Valsartan", []), ("Telmisartan", []), ("Metoprolol", []),
    ("Atenolol", []), ("Bisoprolol", []), ("Carvedilol", []), ("Hydrochlorothiazide", ["HCTZ"]),
    ("Furosemide", ["Lasix"]), ("Spironolactone", []), ("Atorvastatin", ["Lipitor"]), ("Rosuvastatin", []),
    ("Simvastatin", []), ("Aspirin", []), ("Clopidogrel", ["Plavix"]), ("Warfarin", ["Coumadin"]),
    ("Apixaban", []), ("Rivaroxaban", []), ("Levothyroxine", ["Synthroid"]), ("Omeprazole", []),
    ("Pantoprazole", []), ("Paracetamol", ["Acetaminophen", "Tylenol"]), ("Ibuprofen", []), ("Naproxen", []),
    ("Amoxicillin", []), ("Penicillin", []), ("Azithromycin", []), ("Ciprofloxacin", []), ("Doxycycline", []),
    ("Cephalexin", []), ("Prednisone", []), ("Prednisolone", []), ("Salbutamol", ["Albuterol", "Ventolin"]),
    ("Budesonide", []), ("Sertraline", []), ("Escitalopram", []), ("Fluoxetine", []), ("Gabapentin", []),
    ("Tramadol", []), ("Morphine", []), ("Cetirizine", []), ("Loratadine", []), ("Montelukast", []),
    ("Allopurinol", []), ("Digoxin", []), ("Diltiazem", []), ("Nitroglycerin", []),
])

CONDITION_ENTRIES: tuple[LexEntry, ...] = _simple(KIND_CONDITION, [
    ("Type 2 diabetes mellitus", ["Type 2 diabetes", "Type II diabetes", "Diabetes mellitus type 2", "T2DM", "NIDDM"]),
    ("Type 1 diabetes mellitus", ["Type 1 diabetes", "Type I diabetes", "T1DM"]),
    ("Diabetes mellitus", ["Diabetes"]), ("Diabetes insipidus", []),
    ("Prediabetes", ["Pre-diabetes", "Impaired fasting glucose"]),
    ("Hypertension", ["High blood pressure", "HTN"]), ("Pulmonary hypertension", []), ("Hypotension", []),
    ("Hyperlipidemia", ["Hyperlipidaemia", "Dyslipidemia", "Dyslipidaemia", "Hypercholesterolemia"]),
    ("Chronic kidney disease", ["CKD", "Chronic renal failure"]), ("Acute kidney injury", ["AKI"]),
    ("Iron deficiency anemia", ["Iron deficiency anaemia"]), ("Anemia", ["Anaemia"]),
    ("Asthma", []), ("Chronic obstructive pulmonary disease", ["COPD"]), ("Pneumonia", []),
    ("Heart failure", ["Congestive heart failure", "CHF"]), ("Atrial fibrillation", ["AFib"]),
    ("Coronary artery disease", ["CAD"]), ("Myocardial infarction", ["Heart attack", "STEMI", "NSTEMI"]),
    ("Stroke", ["Cerebrovascular accident", "CVA"]), ("Hypothyroidism", []), ("Hyperthyroidism", []),
    ("Obesity", []), ("Depression", ["Major depressive disorder", "MDD"]), ("Anxiety", []),
    ("Urinary tract infection", ["UTI"]), ("Hypokalemia", ["Hypokalaemia"]), ("Hyperkalemia", ["Hyperkalaemia"]),
    ("Hyponatremia", ["Hyponatraemia"]), ("Hypoglycemia", ["Hypoglycaemia"]), ("Hyperglycemia", ["Hyperglycaemia"]),
    ("Gout", []), ("Osteoarthritis", []), ("Diabetic neuropathy", []), ("Peripheral neuropathy", []),
    ("Diabetic retinopathy", []), ("Diabetic nephropathy", []), ("Sepsis", []), ("Cirrhosis", []),
])

SYMPTOM_ENTRIES: tuple[LexEntry, ...] = _simple(KIND_SYMPTOM, [
    ("Chest pain", []), ("Shortness of breath", ["Dyspnea", "Dyspnoea", "SOB", "Breathlessness"]),
    ("Cough", []), ("Fever", []), ("Headache", []), ("Nausea", []), ("Vomiting", []), ("Fatigue", []),
    ("Dizziness", []), ("Edema", ["Oedema", "Peripheral edema"]), ("Abdominal pain", []),
    ("Diarrhea", ["Diarrhoea"]), ("Weight loss", []), ("Palpitations", []), ("Polyuria", []),
    ("Polydipsia", []), ("Blurred vision", []), ("Dysuria", []), ("Rash", []), ("Sore throat", []),
])


def lexicon_sizes() -> dict[str, int]:
    return {
        "lab_tests": len(LAB_ENTRIES),
        "vital_signs": len(VITAL_ENTRIES),
        "medications": len(MEDICATION_ENTRIES),
        "conditions": len(CONDITION_ENTRIES),
        "symptoms": len(SYMPTOM_ENTRIES),
    }
