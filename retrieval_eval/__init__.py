"""Retrieval evaluation metrics and benchmark helpers (Phase 7). Pure Python; no database."""

from retrieval_eval.metrics import aggregate, precision_at_k, recall_at_k, reciprocal_rank
from retrieval_eval.benchmark import Judgment, Query, load_queries, matches, resolve_relevant

__all__ = [
    "Judgment", "Query", "aggregate", "load_queries", "matches", "precision_at_k", "recall_at_k",
    "reciprocal_rank", "resolve_relevant",
]
