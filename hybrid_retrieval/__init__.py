"""Hybrid retrieval and evidence ranking (Phase 7).

A pure library (no FastAPI, no database). It analyses a free-text query, computes six transparent, documented
relevance components per evidence item (semantic, keyword, entity, temporal, confidence, source) and fuses them with a
configurable weighted sum. Every component value is returned so any rank can be explained. See docs/retrieval.md.
"""

from hybrid_retrieval.bm25 import BM25Index, tokenize
from hybrid_retrieval.query import QueryAnalysis, analyze_query
from hybrid_retrieval.ranking import (
    COMPONENTS,
    FORMULA,
    EvidenceFeatures,
    ScoredItem,
    Weights,
    fuse,
    rank,
    score_components,
)

__all__ = [
    "BM25Index", "COMPONENTS", "EvidenceFeatures", "FORMULA", "QueryAnalysis", "ScoredItem", "Weights",
    "analyze_query", "fuse", "rank", "score_components", "tokenize",
]
