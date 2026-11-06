"""Evidence index (Phase 6): turn ClinicalEvidence into searchable vectors and search them.

A pure library (no FastAPI, no database): it builds the text that is embedded, embeds it with a pluggable
embedder, and searches vectors with an exact nearest-neighbour index. Provenance is NOT stored here: the index
only knows opaque evidence ids; the application resolves them back to the stored evidence row, document, page
and source region. See docs/evidence-index.md, docs/embedding-strategy.md and docs/retrieval.md.
"""

from evidence_index.embedders import (
    HASHING_VERSION,
    Embedder,
    EmbedderConfig,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    get_embedder,
)
from evidence_index.errors import EmbeddingUnavailableError, VectorBackendUnavailableError
from evidence_index.text import TEXT_VERSION, build_embedding_text
from evidence_index.vector_index import ScoredId, VectorIndex, create_vector_index, vector_backend_status

__all__ = [
    "HASHING_VERSION", "TEXT_VERSION", "Embedder", "EmbedderConfig", "EmbeddingUnavailableError", "HashingEmbedder",
    "ScoredId", "SentenceTransformerEmbedder", "VectorBackendUnavailableError", "VectorIndex",
    "build_embedding_text", "create_vector_index", "get_embedder", "vector_backend_status",
]
