"""Ranking metrics. `ranked` is the list of returned ids best-first; `relevant` the set of relevant ids (non-empty).

Precision@K  = (relevant items among the first K results) / K          (K is fixed: missing results count as misses)
Recall@K     = (relevant items among the first K results) / |relevant|
RR           = 1 / rank of the first relevant result, 0 if none is returned; MRR is the mean over queries.
"""

from typing import Iterable, Sequence


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return sum(1 for r in ranked[:k] if r in relevant) / k


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall is undefined without relevant items")
    return sum(1 for r in ranked[:k] if r in relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for position, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / position
    return 0.0


def aggregate(runs: Iterable[tuple[Sequence[str], set[str]]], ks: Sequence[int] = (1, 3, 5, 10)) -> dict:
    """Macro-average over queries: {"n", "mrr", "precision@k", "recall@k"}."""
    runs = list(runs)
    n = len(runs)
    if n == 0:
        return {"n": 0, "mrr": None, **{f"precision@{k}": None for k in ks}, **{f"recall@{k}": None for k in ks}}
    out: dict = {"n": n, "mrr": sum(reciprocal_rank(r, rel) for r, rel in runs) / n}
    for k in ks:
        out[f"precision@{k}"] = sum(precision_at_k(r, rel, k) for r, rel in runs) / n
        out[f"recall@{k}"] = sum(recall_at_k(r, rel, k) for r, rel in runs) / n
    return out
