"""Metric formulas verified on hand-computed toy rankings (this tests the arithmetic, not retrieval quality)."""

import json
import pytest

from retrieval_eval import Judgment, aggregate, load_queries, matches, precision_at_k, recall_at_k, reciprocal_rank, resolve_relevant


def test_precision_recall_rr_by_hand():
    ranked, relevant = ["a", "x", "b", "y", "z"], {"a", "b", "c"}
    assert precision_at_k(ranked, relevant, 1) == 1.0
    assert precision_at_k(ranked, relevant, 3) == pytest.approx(2 / 3)
    assert precision_at_k(ranked, relevant, 10) == pytest.approx(0.2)  # K fixed: missing results are misses
    assert recall_at_k(ranked, relevant, 3) == pytest.approx(2 / 3) and recall_at_k(ranked, relevant, 1) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x", "y", "b"], relevant) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], relevant) == 0.0 and reciprocal_rank([], relevant) == 0.0


def test_invalid_arguments():
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, 0)
    with pytest.raises(ValueError):
        recall_at_k(["a"], set(), 3)


def test_aggregate_is_macro_average():
    m = aggregate([(["a", "x"], {"a"}), (["x", "a"], {"a"})], ks=(1, 2))
    assert m["n"] == 2 and m["mrr"] == pytest.approx(0.75) and m["precision@1"] == 0.5 and m["recall@2"] == 1.0
    assert aggregate([], ks=(1,))["mrr"] is None


def item(**kw):
    base = dict(evidence_id="e1", document_filename="a.pdf", entity_name="Potassium", entity_type="lab_result",
                date_iso="2026-05-03", value_text="4.4", assertion="affirmed")
    base.update(kw)
    return base


def test_judgment_matching_requires_all_given_fields():
    assert matches(Judgment("a.pdf", entity_name="Potassium"), item())
    assert matches(Judgment("a.pdf", entity_name="Potassium", date_iso="2026-05-03", value_text="4.4"), item())
    assert not matches(Judgment("b.pdf", entity_name="Potassium"), item())
    assert not matches(Judgment("a.pdf", entity_name="Potassium", date_iso="2026-08-12"), item())
    assert matches(Judgment("a.pdf"), item())


def test_resolve_relevant_reports_unresolved(tmp_path):
    from retrieval_eval import Query
    q = Query("q", "dev", "c", "t", (Judgment("a.pdf", entity_name="Potassium"), Judgment("a.pdf", entity_name="Missing")))
    relevant, unresolved = resolve_relevant(q, [item(), item(evidence_id="e2", entity_name="Sodium")])
    assert relevant == {"e1"} and unresolved == [Judgment("a.pdf", entity_name="Missing")]


def test_load_queries_validates(tmp_path):
    good = {"queries": [{"id": "q1", "split": "dev", "category": "c", "text": "t", "judgments": [{"document": "a.pdf"}]}]}
    p = tmp_path / "q.json"
    p.write_text(json.dumps(good))
    assert load_queries(p)[0].judgments == (Judgment("a.pdf"),)
    for bad in ({"queries": good["queries"] * 2},
                {"queries": [{**good["queries"][0], "split": "val"}]},
                {"queries": [{**good["queries"][0], "judgments": []}]}):
        p.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_queries(p)


def test_shipped_benchmark_file_is_valid_and_documents_exist():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "data" / "benchmark" / "retrieval"
    queries = load_queries(root / "queries.json")
    assert {q.split for q in queries} == {"dev", "test"} and len(queries) >= 40
    docs = {p.name for p in (root / "documents").glob("*.pdf")}
    assert docs and all(j.document in docs for q in queries for j in q.judgments)
