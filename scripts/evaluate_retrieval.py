#!/usr/bin/env python3
"""Reproducible retrieval benchmark (Phase 7): Precision@K, Recall@K and MRR on the SYNTHETIC benchmark.

    python scripts/evaluate_retrieval.py            # development: tunes weights on the DEV split, prints DEV results only
    python scripts/evaluate_retrieval.py --final    # also evaluates the held-out TEST split (run once, after the design is fixed)

What it does: ingests data/benchmark/retrieval/documents/*.pdf through the real pipeline (text/OCR, tables, clinical
extraction, indexing) into a throw-away SQLite database, resolves the hand-written relevance judgments against the extracted
evidence, ranks every query with each system, and measures. Weights are chosen on dev only (grid search; centroid of the
best plateau). Nothing here is a clinical-quality claim: 44 short queries over 6 synthetic documents, default
embedding = hashing (lexical). Results are written to data/benchmark/retrieval/results.json.
"""

import argparse
import itertools
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
BENCH = ROOT / "data" / "benchmark" / "retrieval"
KS = (1, 3, 5, 10)
GRID = {
    "semantic": (0, 0.5, 1, 2), "keyword": (0, 0.5, 1, 2), "entity": (0, 0.5, 1, 2), "temporal": (0, 0.5, 1, 2),
    "confidence": (0, 0.1, 0.3), "source": (0, 0.1),
}
MAX_RANKED = 50


def setup_app(workdir: str):
    os.environ.update({"LOG_DIR": "", "UPLOAD_DIR": f"{workdir}/uploads", "IMAGE_DIR": f"{workdir}/images",
                       "EMBEDDING_BACKEND": os.environ.get("EMBEDDING_BACKEND", "hashing"), "VECTOR_BACKEND": os.environ.get("VECTOR_BACKEND", "faiss"),
                       "DATABASE_URL": "sqlite://"})
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401
    from app.core.config import get_settings
    from app.db.base import Base
    from app.db.session import get_session, get_session_factory
    from app.main import create_app

    get_settings.cache_clear()
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    application = create_app()

    def _session():
        with factory() as s:
            yield s

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_session_factory] = lambda: factory
    return TestClient(application), factory, get_settings()


def ingest(client) -> list[dict]:
    for pdf in sorted((BENCH / "documents").glob("*.pdf")):
        doc = client.post("/api/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
        doc.raise_for_status()
        client.post(f"/api/documents/{doc.json()['id']}/process").raise_for_status()
    docs = client.get("/api/documents?limit=100").json()["items"]
    bad = [d["original_filename"] for d in docs if d["index_status"] != "completed"]
    if bad:
        sys.exit(f"Indexing did not complete for: {bad}")
    return client.get("/api/evidence?limit=1000").json()["items"]


def hybrid_name(settings) -> str:
    from app.services.evidence_index import current_model_name
    return current_model_name(settings)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="also evaluate the held-out test split")
    ap.add_argument("--out", default=str(BENCH / "results.json"))
    args = ap.parse_args()

    from retrieval_eval import aggregate, load_queries, resolve_relevant
    from hybrid_retrieval import COMPONENTS, Weights, rank

    with tempfile.TemporaryDirectory() as workdir:
        client, factory, settings = setup_app(workdir)
        from app.services import hybrid_retrieval as hybrid

        evidence = ingest(client)
        queries = load_queries(BENCH / "queries.json")
        splits = ("dev", "test") if args.final else ("dev",)
        queries = [q for q in queries if q.split in splits]  # test queries are not even loaded unless --final

        prepared, relevant, unresolved = {}, {}, {}
        with factory() as session:
            for q in queries:
                rel, missing = resolve_relevant(q, evidence)
                if missing:
                    unresolved[q.id] = [vars(j) for j in missing]
                if not rel:
                    continue  # nothing resolvable: not scored (reported below)
                relevant[q.id] = rel
                prepared[q.id] = hybrid.prepare(session, settings, q.text)

        def ranking(qid: str, weights: Weights) -> list[str]:
            ranked = rank(prepared[qid].items, weights)
            return [r.features.id for r in ranked if r.final_score > 0][:MAX_RANKED]

        def evaluate(weights: Weights, split: str) -> dict:
            ids = [q.id for q in queries if q.split == split and q.id in relevant]
            return aggregate(((ranking(i, weights), relevant[i]) for i in ids), KS)

        # ---- weight selection on DEV only
        keys = list(GRID)
        scored_grid = []
        for values in itertools.product(*(GRID[k] for k in keys)):
            w = dict(zip(keys, values))
            if w["semantic"] == w["keyword"] == w["entity"] == w["temporal"] == 0:
                continue
            m = evaluate(Weights(**w), "dev")
            scored_grid.append(((m["mrr"], m["precision@5"], m["recall@10"]), w))
        best_key = max(k for k, _ in scored_grid)
        plateau = [w for k, w in scored_grid if k == best_key]
        tuned = {c: round(sum(w[c] for w in plateau) / len(plateau), 2) for c in COMPONENTS}  # rounded = what ships

        systems = {
            "semantic_only (Phase 6 behaviour)": Weights.only("semantic"),
            "keyword_only (BM25)": Weights.only("keyword"),
            "entity_only": Weights.only("entity"),
            "equal_weights (all 1)": Weights(1, 1, 1, 1, 1, 1),
            "initial_default (1,1,1,1,0.1,0.1)": Weights(),
            "tuned_on_dev (plateau centroid)": Weights(**tuned),
        }
        results = {name: {s: evaluate(w, s) for s in splits} for name, w in systems.items()}

        per_query = {}
        if args.final:
            for q in queries:
                if q.id not in relevant:
                    continue
                row = {"split": q.split, "category": q.category, "text": q.text, "relevant_items": len(relevant[q.id])}
                for name, w in systems.items():
                    r = ranking(q.id, w)
                    pos = next((n for n, i in enumerate(r, 1) if i in relevant[q.id]), None)
                    row[name] = pos
                per_query[q.id] = row

        report = {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "environment": {"python": platform.python_version(), "embedding": settings.embedding_backend + ("" if settings.embedding_backend != "hashing" else " (lexical, no trained model)"), "embedding_model": hybrid_name(settings),
                            "vector_backend": settings.vector_backend},
            "benchmark": {"documents": len(list((BENCH / 'documents').glob('*.pdf'))), "evidence_items": len(evidence),
                          "queries_scored": {s: sum(1 for q in queries if q.split == s and q.id in relevant) for s in splits},
                          "queries_total": {s: sum(1 for q in queries if q.split == s) for s in splits},
                          "unresolved_judgments": unresolved},
            "weight_selection": {"split": "dev", "grid_size": len(scored_grid), "best_dev_key(mrr,p@5,r@10)": best_key,
                                 "plateau_size": len(plateau), "tuned_weights": tuned},
            "results": results,
            "per_query_first_relevant_rank": per_query,
            "caveats": [
                "Small synthetic benchmark (6 documents, 44 queries): differences of a few points are noise.",
                "Weights were tuned on the dev split and the final design was fixed before the test split was evaluated.",
                "Default embedding is lexical (hashing). The sentence-transformers backend has not been evaluated.",
                "Judgments were written by the developer from the document text; no inter-annotator agreement exists.",
            ],
        }
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")

    def row(name, m):
        return f"{name:38} n={m['n']:2}  MRR={m['mrr']:.3f}  " + "  ".join(f"P@{k}={m[f'precision@{k}']:.3f}" for k in KS) + "  " + "  ".join(f"R@{k}={m[f'recall@{k}']:.3f}" for k in (3, 5, 10))

    print(f"\nEvidence items: {len(evidence)}; unresolved judgments: {sum(len(v) for v in unresolved.values())} {list(unresolved)}")
    print(f"Tuned weights (dev plateau of {len(plateau)} configs): {tuned}")
    for s in splits:
        print(f"\n== {s.upper()} split")
        for name, by in results.items():
            print(row(name, by[s]))
    if not args.final:
        print("\n(test split not evaluated; run with --final once the design is fixed)")
    print(f"\nwritten: {args.out}")


if __name__ == "__main__":
    main()
