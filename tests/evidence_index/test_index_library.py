"""Phase 6 library tests: embedding text, embedders, vector indexes. Synthetic strings only."""

import types

import numpy as np
import pytest

from evidence_index import (
    EmbedderConfig, EmbeddingUnavailableError, HashingEmbedder, VectorBackendUnavailableError,
    build_embedding_text, create_vector_index, get_embedder,
)
from evidence_index import embedders as emb_module


def ev(**kw):
    base = dict(entity_type="lab_result", entity_name="Hemoglobin A1c", assertion="affirmed", value_text="7.8",
                value_comparator=None, unit_text="%", reference_text=None, abnormal_flag=None, date_iso=None,
                date_text=None, source_text="HbA1c was 7.8 % on 12-Aug-2026.")
    base.update(kw)
    return types.SimpleNamespace(**base)


# ---- embedding text
def test_text_uses_only_stored_fields():
    text = build_embedding_text(ev(date_iso="2026-08-12", abnormal_flag="high", reference_text="4.0 - 5.6"))
    assert text == ("Laboratory result: Hemoglobin A1c. Value: 7.8 %. Reference range: 4.0 - 5.6. Flag: high. "
                    "Date: 2026-08-12. Source: HbA1c was 7.8 % on 12-Aug-2026.")


def test_text_marks_negation_and_is_none_safe():
    text = build_embedding_text(ev(entity_type="symptom", entity_name="Chest pain", assertion="negated",
                                   value_text=None, unit_text=None, source_text="Patient denies chest pain."))
    assert "negated" in text and "Value:" not in text


def test_text_does_not_repeat_unit_and_truncates():
    assert "mg mg" not in build_embedding_text(ev(entity_type="medication", value_text="500 mg", unit_text="mg"))
    assert len(build_embedding_text(ev(source_text="x " * 2000))) < 1100


def test_text_is_deterministic():
    assert build_embedding_text(ev()) == build_embedding_text(ev())


# ---- hashing embedder
def test_hashing_is_deterministic_normalised_and_named():
    e = HashingEmbedder(256)
    a, b = e.embed(["Chest pain", "Chest pain"])
    assert np.array_equal(a, b) and abs(np.linalg.norm(a) - 1) < 1e-5 and a.dtype == np.float32
    assert e.name == "hashing-v1-d256" and not e.is_semantic and e.embed(["x"]).shape == (1, 256)


def test_hashing_empty_text_is_zero_vector_not_nan():
    v = HashingEmbedder().embed(["", "the of and"])
    assert not np.isnan(v).any() and float(np.abs(v).sum()) == 0.0


def test_hashing_ranks_lexical_overlap_first_and_is_not_semantic():
    e = HashingEmbedder()
    docs = e.embed(["Symptom: Chest pain. Source: Patient denies chest pain.", "Medication: Metformin 500 mg",
                    "Laboratory result: Glucose 5.4 mmol/L"])
    q = e.embed(["chest pain"])[0]
    assert int(np.argmax(docs @ q)) == 0
    sugar = e.embed(["blood sugar"])[0]  # synonym of glucose: a lexical embedder must NOT be able to link them
    assert (docs @ sugar)[2] < 0.3


def test_hashing_dimension_validated():
    with pytest.raises(ValueError):
        HashingEmbedder(4)


def test_get_embedder_factory_and_errors(monkeypatch):
    assert get_embedder(EmbedderConfig(backend="hashing", dimension=128)).dimension == 128
    with pytest.raises(EmbeddingUnavailableError):
        get_embedder(EmbedderConfig(backend="nope"))


# ---- sentence-transformers adapter (stubbed: no model is downloaded in tests)
def test_sentence_transformer_adapter_with_stub(monkeypatch):
    class Stub:
        def __init__(self, model, local_files_only=False):
            self.args = (model, local_files_only)
        def get_sentence_embedding_dimension(self):
            return 3
        def encode(self, texts, **kw):
            return np.array([[3.0, 4.0, 0.0]] * len(texts))
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Stub))
    e = emb_module.SentenceTransformerEmbedder("some/model", local_files_only=True)
    assert e.name == "some/model" and e.dimension == 3 and e.is_semantic and e._model.args == ("some/model", True)
    assert np.allclose(e.embed(["a", "b"]), [[0.6, 0.8, 0.0]] * 2)


def test_sentence_transformer_missing_package_gives_fix_hint(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)
    with pytest.raises(EmbeddingUnavailableError, match="requirements-embeddings.txt"):
        emb_module.SentenceTransformerEmbedder("m")


def test_sentence_transformer_load_failure_is_clear_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=boom))
    with pytest.raises(EmbeddingUnavailableError, match="could not be loaded"):
        emb_module.SentenceTransformerEmbedder("m")


# ---- vector indexes
@pytest.fixture(params=["numpy", "faiss"])
def backend(request):
    if request.param == "faiss":
        pytest.importorskip("faiss")
    return request.param


def _vectors():
    e = HashingEmbedder(256)
    texts = ["chest pain denied", "metformin 500 mg", "hemoglobin a1c 7.8", "blood pressure 150/95", "chest x-ray report"]
    return [f"id{i}" for i in range(5)], e.embed(texts), e


def test_search_exact_ranking(backend):
    ids, m, e = _vectors()
    hits = create_vector_index(backend, ids, m).search(e.embed(["chest pain"])[0], 3)
    assert hits[0].id == "id0" and [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_prefilter_returns_k_from_allowed_only(backend):
    ids, m, e = _vectors()
    hits = create_vector_index(backend, ids, m).search(e.embed(["chest pain"])[0], 2, {"id1", "id2", "id3"})
    assert len(hits) == 2 and {h.id for h in hits} <= {"id1", "id2", "id3"}


def test_empty_cases(backend):
    ids, m, e = _vectors()
    q = e.embed(["x"])[0]
    assert create_vector_index(backend, ids, m).search(q, 3, set()) == []
    assert create_vector_index(backend, ids, m).search(q, 0) == []
    assert create_vector_index(backend, [], np.zeros((0, 256), dtype=np.float32)).search(q, 3) == []
    assert len(create_vector_index(backend, ids, m).search(q, 100)) == 5
    assert create_vector_index(backend, ids, m).search(q, 3, {"unknown"}) == []


def test_backends_agree():
    pytest.importorskip("faiss")
    ids, m, e = _vectors()
    q = e.embed(["chest x-ray"])[0]
    a = create_vector_index("numpy", ids, m).search(q, 5)
    b = create_vector_index("faiss", ids, m).search(q, 5)
    assert [h.id for h in a] == [h.id for h in b] and np.allclose([h.score for h in a], [h.score for h in b], atol=1e-5)


def test_shape_mismatch_and_unknown_backend():
    with pytest.raises(ValueError):
        create_vector_index("numpy", ["a"], np.zeros((2, 4), dtype=np.float32))
    with pytest.raises(VectorBackendUnavailableError):
        create_vector_index("nope", [], np.zeros((0, 4), dtype=np.float32))
