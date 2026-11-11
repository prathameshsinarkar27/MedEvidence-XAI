"""Tiny evidence factory for the Phase 8 library tests (no database)."""

from evidence_reasoning import VEvidence

_counter = {"n": 0}


def ev(name="Hemoglobin A1c", value="7.8", date="2026-08-12", *, etype="lab_result", unit="%", assertion="affirmed",
       modality="text", conf=0.9, sem=0.5, rank=None, doc="d1", page=1, text=None, start=None, end=None, id=None, **kw):
    _counter["n"] += 1
    n = _counter["n"]
    numeric = kw.pop("numeric", None)
    if numeric is None and value is not None and "/" not in str(value):
        try:
            numeric = float(str(value).split()[0])
        except ValueError:
            numeric = None
    return VEvidence(
        id=id or f"e{n}", document_id=doc, document_filename=f"{doc}.pdf", page_number=page, entity_type=etype, entity_name=name,
        assertion=assertion, modality=modality, extraction_confidence=conf, source_text=text if text is not None else f"{name} {value}",
        source_start=start, source_end=end, value_text=value, value_numeric=numeric, unit_normalized=unit if value is not None else None,
        date_iso=date, retrieval_rank=rank if rank is not None else n, semantic=sem, order=(doc, n), **kw)


def bp(sys_, dia, date="2026-08-12", **kw):
    return ev("Blood pressure", f"{sys_}/{dia}", date, etype="vital_sign", unit="mmHg", numeric=float(sys_),
              attributes={"systolic": sys_, "diastolic": dia}, **kw)


def finding(name, etype="condition", assertion="affirmed", date=None, **kw):
    return ev(name, None, date, etype=etype, assertion=assertion, unit=None, **kw)
