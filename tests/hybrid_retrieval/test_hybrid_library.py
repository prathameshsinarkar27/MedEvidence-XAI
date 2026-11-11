"""Phase 7 library tests: BM25, query analysis, component scoring, fusion. Synthetic strings only."""

import pytest

from hybrid_retrieval import (
    BM25Index, EvidenceFeatures, Weights, analyze_query, fuse, rank, score_components, tokenize,
)


def feat(id, name="Hemoglobin A1c", date=None, conf=0.9, modality="text", page=1, ocr=None):
    return EvidenceFeatures(id=id, document_id="d", page_number=page, entity_name=name, modality=modality,
                            extraction_confidence=conf, date_iso=date, ocr_confidence=ocr)


# ---- BM25
def test_bm25_ranks_term_matches_and_omits_non_matches():
    idx = BM25Index({"a": "chest pain denied", "b": "metformin 500 mg", "c": "pain in the knee and chest pain"})
    s = idx.score(tokenize("chest pain"))
    assert set(s) == {"a", "c"} and s["a"] > 0 and "b" not in s
    assert idx.score(tokenize("zzz")) == {} and idx.score([]) == {}


def test_bm25_rare_terms_weigh_more_and_allowed_restricts():
    idx = BM25Index({"a": "common rare", "b": "common", "c": "common", "d": "common"})
    s = idx.score(["common", "rare"])
    assert s["a"] > s["b"]
    assert set(idx.score(["common"], allowed={"b", "c"})) == {"b", "c"}
    assert idx.matched_terms(["common", "rare", "none"], "a") == ["common", "rare"]


def test_tokenizer_keeps_numbers_and_drops_stopwords():
    assert tokenize("The HbA1c was 7.8 % on 12-Aug-2026") == ["hba1c", "7.8", "12", "aug", "2026"]


# ---- query analysis
@pytest.mark.parametrize("text,entities", [
    ("hba1c", ["Hemoglobin A1c"]), ("blood sugar", ["Glucose"]), ("high blood pressure", ["Hypertension"]),
    ("wbc count", ["White blood cell count"]), ("metformin and INR", ["Metformin", "INR"]), ("hello", []),
])
def test_query_entities_use_lexicon_synonyms(text, entities):
    assert analyze_query(text).entities == entities


def test_query_dates_and_periods():
    a = analyze_query("HbA1c on 12-Aug-2026")
    assert a.periods == [("2026-08-12", "2026-08-12")] and a.recency is None
    assert analyze_query("potassium in August 2026").periods == [("2026-08-01", "2026-08-31")]
    assert analyze_query("results in 2026").periods == [("2026-01-01", "2026-12-31")]
    assert analyze_query("feb 2024").periods == [("2024-02-01", "2024-02-29")]  # leap year
    assert analyze_query("created 2026-02-30").periods == []  # impossible date is not invented


def test_ambiguous_numeric_date_keeps_both_readings():
    a = analyze_query("labs 03/04/2026")
    assert set(a.periods) == {("2026-04-03", "2026-04-03"), ("2026-03-04", "2026-03-04")} and a.notes


def test_recency_and_page_hints():
    assert analyze_query("latest HbA1c").recency == "latest"
    assert analyze_query("earliest potassium").recency == "earliest"
    assert analyze_query("latest on 12-Aug-2026").recency is None  # explicit date wins, with a note
    assert analyze_query("sodium page 3").page_hint == 3 and analyze_query("sodium").page_hint is None


# ---- components
def comps(query, items, semantic=None, keyword=None):
    return {s.features.id: s for s in score_components(analyze_query(query), items, semantic or {}, keyword or {})}


def test_entity_score_exact_partial_none():
    s = comps("blood sugar", [feat("g", "Glucose"), feat("f", "Fasting glucose"), feat("k", "Potassium")])
    assert (s["g"].components["entity"], s["f"].components["entity"], s["k"].components["entity"]) == (1.0, 0.5, 0.0)


def test_keyword_normalised_by_best_and_semantic_clipped():
    s = comps("x", [feat("a"), feat("b")], semantic={"a": 0.4, "b": -0.2}, keyword={"a": 4.0, "b": 1.0})
    assert s["a"].components["keyword"] == 1.0 and s["b"].components["keyword"] == 0.25
    assert s["a"].components["semantic"] == 0.4 and s["b"].components["semantic"] == 0.0


def test_period_scoring_inside_outside_and_undated():
    items = [feat("in", date="2026-08-12"), feat("near", date="2026-09-11"), feat("far", date="2025-01-01"), feat("none")]
    s = comps("hba1c on 12-Aug-2026", items)
    assert s["in"].components["temporal"] == 1.0
    assert 0 < s["far"].components["temporal"] < s["near"].components["temporal"] < 0.5
    assert s["none"].components["temporal"] == 0.0 and "no date" in s["none"].temporal_note


def test_latest_and_earliest_rank_only_entity_matched_dated_items():
    items = [feat("old", date="2026-05-03"), feat("mid", date="2026-08-12"), feat("new", date="2026-09-15"),
             feat("other", "Potassium", date="2026-12-01"), feat("undated")]
    s = comps("latest HbA1c", items)
    assert (s["old"].components["temporal"], s["new"].components["temporal"]) == (0.0, 1.0)
    assert 0 < s["mid"].components["temporal"] < 1
    assert s["other"].components["temporal"] == 0.0 and s["undated"].components["temporal"] == 0.0
    e = comps("earliest HbA1c", items)
    assert (e["old"].components["temporal"], e["new"].components["temporal"]) == (1.0, 0.0)


def test_latest_with_single_dated_item_scores_one_and_no_temporal_without_trigger():
    assert comps("latest HbA1c", [feat("a", date="2026-01-01")])["a"].components["temporal"] == 1.0
    assert comps("HbA1c", [feat("a", date="2026-01-01")])["a"].components["temporal"] == 0.0


def test_source_score_ocr_confidence_and_page_hint():
    s = comps("sodium page 2", [feat("t", page=2), feat("o", page=2, modality="ocr", ocr=80), feat("w", page=1)])
    assert s["t"].components["source"] == 1.0 and s["o"].components["source"] == 0.8 and s["w"].components["source"] == 0.5
    assert comps("sodium", [feat("o", modality="image_ocr", ocr=50)])["o"].components["source"] == 0.5
    assert comps("sodium", [feat("o", modality="ocr", ocr=None)])["o"].components["source"] == 1.0


# ---- fusion
def test_fusion_is_the_documented_weighted_sum():
    item = comps("hba1c", [feat("a", conf=0.5)], semantic={"a": 0.2}, keyword={"a": 1.0})["a"]
    w = Weights(semantic=2, keyword=1, entity=3, temporal=5, confidence=1, source=0.5)
    assert fuse(item, w) == pytest.approx(2 * 0.2 + 1 * 1.0 + 3 * 1.0 + 5 * 0.0 + 1 * 0.5 + 0.5 * 1.0)


def test_rank_orders_by_score_with_deterministic_ties():
    items = score_components(analyze_query("zzz"), [feat("b", "X"), feat("a", "X")], {}, {})
    assert [r.features.id for r in rank(items, Weights())] == ["a", "b"]  # last resort: id order
    from dataclasses import replace
    ordered = [replace(feat("z", "X"), order=("a.pdf", 5)), replace(feat("a", "X"), order=("b.pdf", 1))]
    scored = score_components(analyze_query("zzz"), ordered, {}, {})
    assert [r.features.id for r in rank(scored, Weights())] == ["z", "a"]  # document name decides, not the id
    items = score_components(analyze_query("zzz"), [feat("lo", conf=0.1), feat("hi", conf=0.9)], {}, {})
    assert [r.features.id for r in rank(items, Weights(confidence=1))] == ["hi", "lo"]


def test_weights_validation_and_only():
    with pytest.raises(ValueError):
        Weights(semantic=-1)
    assert Weights.only("keyword").as_dict()["keyword"] == 1.0 and Weights.only("keyword").total == 1.0
