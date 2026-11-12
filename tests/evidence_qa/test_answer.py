"""Phase 9 library tests (no database): composer, guard, abstention, confidence, explanation, LLM provider with a stub server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from evidence_qa import (
    ABSTENTION_MESSAGE,
    AnswerContext,
    Claim,
    CtxConflict,
    CtxEvidence,
    Draft,
    OpenAICompatibleProvider,
    ProviderError,
    build_answer,
    build_messages,
    is_local_url,
    parse_response,
    selection_reasons,
    validate,
)


def item(i, name="Hemoglobin A1c", value="7.8", date="2026-08-12", unit="%", etype="lab_result", assertion="affirmed", role="supporting",
         text=None, score=0.9, **kw):
    return CtxEvidence(id=i, entity_name=name, entity_type=etype, assertion=assertion, document_filename="r.pdf", page_number=1,
                       source_text=text or f"{name} {value} {unit or ''} on {date}.", mention_text=name, value_text=value, unit_text=unit,
                       date_iso=date, extraction_confidence=0.9, evidence_score=score, role=role,
                       selection={"retrieval_rank": 1, "retrieval_components": {"entity": {"contribution": 1.0}},
                                  "terms": {"entity": {"score": 1.0}}, "constraints": {}, "requested": ["value"]}, **kw)


def ctx(supporting, state="supported", primary="value_lookup", context=(), conflicts=(), conflicting=(), advice=False, reasons=()):
    return AnswerContext(question="q", primary_type=primary, requested=["value"], entities=[], recency=None, periods=[], state=state,
                         state_reasons=list(reasons), advice_request=advice, supporting=list(supporting), context=list(context),
                         conflicting_ids=list(conflicting), conflicts=list(conflicts))


def test_value_answer_cites_evidence():
    r = build_answer(ctx([item("a")]))
    assert r.status == "answered" and r.text == "Hemoglobin A1c was 7.8 % on 2026-08-12. [1]"
    assert r.claims[0].evidence_ids == ["a"] and r.provider_used == "extractive"


def test_identical_statements_in_several_places_are_one_claim_with_all_sources():
    r = build_answer(ctx([item("a"), item("b")]))
    assert len(r.claims) == 1 and r.claims[0].evidence_ids == ["a", "b"] and r.text.count("7.8") == 1


def test_every_claim_cites_evidence_in_every_status():
    a, b = item("a", "Blood pressure", "120/80", unit="mmHg", etype="vital_sign"), item("b", "Blood pressure", "150/95", unit="mmHg", etype="vital_sign")
    pair = CtxConflict(("a", "b"), "Blood pressure", "possible_contradiction", "moderate", True)
    for c in (ctx([item("a")]), ctx([a, b], "conflicting", conflicts=[pair], conflicting=["a", "b"])):
        r = build_answer(c)
        assert r.claims and all(cl.evidence_ids for cl in r.claims)


def test_conflict_is_reported_and_not_resolved():
    a, b = item("a", "Blood pressure", "120/80", unit="mmHg", etype="vital_sign"), item("b", "Blood pressure", "150/95", unit="mmHg", etype="vital_sign")
    pair = CtxConflict(("a", "b"), "Blood pressure", "possible_contradiction", "moderate", True)
    r = build_answer(ctx([a, b], "conflicting", conflicts=[pair], conflicting=["a", "b"]))
    assert r.status == "conflict_reported" and "differing values" in r.text and "120/80" in r.text and "150/95" in r.text
    assert any("does not decide" in c for c in r.caveats) and r.confidence.answer_support["label"] == "conflicting"


def test_negated_and_uncertain_assertions_are_worded_as_such():
    n = build_answer(ctx([item("a", "Chest pain", None, None, None, etype="symptom", assertion="negated", text="Patient denies chest pain.")]))
    u = build_answer(ctx([item("b", "Pneumonia", None, None, None, etype="condition", assertion="uncertain", text="Possible pneumonia.")]))
    assert "negated" in n.text and "uncertainty" in u.text


def test_temporal_change_states_direction_only():
    a, b = item("a", value="8.2", date="2026-05-03"), item("b", value="7.8", date="2026-08-12")
    pair = CtxConflict(("a", "b"), "Hemoglobin A1c", "temporal_change", "moderate", True, "decreased")
    r = build_answer(ctx([a, b], primary="comparison", conflicts=[pair]))
    assert "decreased" in r.text and "not a clinical judgement" in r.text and "improv" not in r.text.lower()


@pytest.mark.parametrize("state,kwargs,reason", [
    ("insufficient_evidence", {}, "insufficient_evidence"),
    ("supported", {"advice": True}, "advice_request_out_of_scope"),
    ("supported", {"supporting": []}, "no_supporting_evidence"),
])
def test_abstention_uses_the_exact_message(state, kwargs, reason):
    supporting = kwargs.pop("supporting", [item("a")])
    r = build_answer(ctx(supporting, state, advice=kwargs.get("advice", False)))
    assert r.status == "abstained" and r.text == ABSTENTION_MESSAGE and r.claims == [] and r.abstention_reason == reason
    assert r.confidence.evidence_confidence["score"] is None


def test_confidence_report_separates_three_measures_and_is_not_certainty():
    r = build_answer(ctx([item("a", score=0.8), item("b", value="7.0", score=0.72)]))
    c = r.confidence
    assert c.model_confidence == {**c.model_confidence, "available": False, "value": None}
    assert c.evidence_confidence["score"] == 0.72 and c.evidence_confidence["basis"].startswith("minimum")
    assert c.answer_support["label"] == "full" and "certainty" in c.evidence_confidence["note"]


# ---- guard ----
def draft(*claims, **kw):
    return Draft([Claim(f"c{n}", t, ids, "fact") for n, (t, ids) in enumerate(claims, 1)], **kw)


@pytest.mark.parametrize("text,ids,code", [
    ("HbA1c was 9.9 % on 2026-08-12.", ["a"], "ungrounded_number"),
    ("HbA1c was 7.8 %.", [], "missing_evidence"),
    ("HbA1c was 7.8 %.", ["zzz"], "unknown_evidence"),
    ("HbA1c was 7.8 %, so the patient should increase treatment.", ["a"], "advice_language"),
    ("x" * 500, ["a"], "claim_too_long"),
])
def test_guard_rejects_ungrounded_claims(text, ids, code):
    assert code in {v.code for v in validate(draft((text, ids)), ctx([item("a")]))}


def test_guard_rejects_a_claim_that_drops_negation_and_unacknowledged_conflict():
    neg = ctx([item("a", "Chest pain", None, None, None, etype="symptom", assertion="negated", text="Patient denies chest pain.")])
    assert "assertion_mismatch" in {v.code for v in validate(draft(("The patient has chest pain.", ["a"])), neg)}
    c = ctx([item("a"), item("b", value="7.0")], "conflicting", conflicting=["a", "b"])
    assert "conflict_not_acknowledged" in {v.code for v in validate(draft(("HbA1c was 7.8 %.", ["a"])), c)}


def test_guard_rejects_evidence_outside_the_verified_context():
    c = ctx([item("a")], context=[item("x", role="context")])
    assert "unknown_evidence" in {v.code for v in validate(draft(("HbA1c was 7.8 %.", ["x"])), c)}


def test_guard_accepts_a_faithful_draft():
    assert validate(draft(("HbA1c was 7.8 % on 2026-08-12 (r.pdf, page 1).", ["a"])), ctx([item("a")])) == []


# ---- explanation ----
def test_selection_reasons_are_built_from_facts():
    text = " ".join(selection_reasons(item("a"), set()))
    assert "rank 1" in text and "entity" in text and "Verification score 0.90" in text and "extraction confidence 0.90" in text
    assert "possible contradiction" in " ".join(selection_reasons(item("a"), {"a"}))


# ---- LLM provider ----
class Stub(BaseHTTPRequestHandler):
    reply = ""
    seen: list = []
    status = 200

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append((self.path, dict(self.headers), body))
        self.send_response(Stub.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": Stub.reply}}]}).encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def stub():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Stub.seen, Stub.status = [], 200
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def provider(url, **kw):
    return OpenAICompatibleProvider(base_url=url, model="stub", timeout=5, **kw)


def test_llm_answer_is_used_when_it_passes_the_guard(stub):
    Stub.reply = json.dumps({"claims": [{"text": "The latest HbA1c in the report was 7.8 % (2026-08-12).", "evidence_ids": ["E1"]}], "caveats": []})
    r = build_answer(ctx([item("a")]), provider(stub, api_key="k1"))
    assert r.provider_used == "openai_compatible" and r.claims[0].evidence_ids == ["a"] and not r.warnings
    path, headers, body = Stub.seen[0]
    assert path == "/v1/chat/completions" and headers["Authorization"] == "Bearer k1" and body["temperature"] == 0.0


def test_llm_output_that_leaves_the_evidence_is_replaced(stub):
    Stub.reply = json.dumps({"claims": [{"text": "HbA1c was 9.9 %, so treatment should be intensified.", "evidence_ids": ["E1"]}]})
    r = build_answer(ctx([item("a")]), provider(stub))
    assert r.provider_used == "extractive" and r.text == "Hemoglobin A1c was 7.8 % on 2026-08-12. [1]"
    assert r.warnings and r.warnings[0].startswith("llm_output_rejected") and "ungrounded_number" in r.warnings[0]


@pytest.mark.parametrize("reply", ["not json", '{"claims": "x"}', "{}"])
def test_malformed_llm_output_falls_back(stub, reply):
    Stub.reply = reply
    r = build_answer(ctx([item("a")]), provider(stub))
    assert r.provider_used == "extractive" and r.warnings[0].startswith("llm_fallback:invalid_model_output")


def test_unreachable_llm_falls_back():
    r = build_answer(ctx([item("a")]), provider("http://127.0.0.1:9/v1"))
    assert r.provider_used == "extractive" and r.warnings[0].startswith("llm_fallback:llm_unavailable")


def test_llm_is_never_called_when_abstaining(stub):
    r = build_answer(ctx([item("a")], "insufficient_evidence"), provider(stub))
    assert r.status == "abstained" and Stub.seen == []


def test_external_endpoint_is_blocked_unless_allowed():
    p = OpenAICompatibleProvider(base_url="https://api.example.invalid/v1", model="m", api_key="secret")
    assert p.external and not is_local_url("https://api.example.invalid/v1")
    with pytest.raises(ProviderError) as e:
        p.generate(ctx([item("a")]))
    assert e.value.code == "external_not_allowed"
    r = build_answer(ctx([item("a")]), p)
    assert r.provider_used == "extractive" and "secret" not in json.dumps(r.warnings)


def test_prompt_contains_only_verified_evidence():
    c = ctx([item("a")], context=[item("x", "Potassium", "4.1", role="context", text="Potassium 4.1 SECRET-CONTEXT")])
    messages, alias = build_messages(c)
    prompt = json.dumps(messages)
    assert "SECRET-CONTEXT" not in prompt and "Potassium" not in prompt and alias == {"E1": "a"}
    assert "do not add medical knowledge" in prompt and "Hemoglobin A1c" in prompt


def test_parse_response_maps_aliases_and_strips_code_fences():
    d = parse_response('```json\n{"claims":[{"text":"t","evidence_ids":["E1"]}],"caveats":["c"],"acknowledges_conflict":true}\n```', {"E1": "a"}, "p")
    assert d.claims[0].evidence_ids == ["a"] and d.caveats == ["c"] and d.acknowledges_conflict and d.provider == "p"


def test_local_url_detection():
    assert is_local_url("http://localhost:11434/v1") and is_local_url("http://127.0.0.1:8080/v1") and not is_local_url("https://api.openai.com/v1")
