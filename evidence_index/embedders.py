"""Embedding backends.

`hashing`: deterministic, offline, no download, no trained model. Feature hashing of word and character n-grams.
  It measures *lexical* overlap, NOT meaning ("sugar" will not match "glucose"). It exists so the whole pipeline
  runs and can be tested anywhere, and is reported as non-semantic wherever it is used.
`sentence-transformers`: a real open-source sentence embedding model (default all-MiniLM-L6-v2), downloaded
  once from the Hugging Face hub (or loaded from a local folder). Optional dependency.

Every embedder returns float32 vectors, L2-normalised, so cosine similarity is an inner product.
"""

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np

from evidence_index.errors import EmbeddingUnavailableError

logger = logging.getLogger(__name__)

HASHING_VERSION = "1"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to was were with that this".split()
)
_WORD_WEIGHT, _BIGRAM_WEIGHT, _CHAR_WEIGHT = 1.0, 0.5, 0.35
_CHAR_NGRAMS = (3, 4)


class Embedder(Protocol):
    name: str  # stored with every vector; a different name means a different vector space
    backend: str
    dimension: int
    is_semantic: bool

    def embed(self, texts: list[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class EmbedderConfig:
    backend: str = "hashing"  # hashing | sentence-transformers
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimension: int = 512  # hashing only
    local_files_only: bool = False  # sentence-transformers: never touch the network
    batch_size: int = 64


def _bucket(feature: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value % dimension, 1.0 if (value >> 40) & 1 else -1.0  # sign hashing reduces collision bias


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class HashingEmbedder:
    backend = "hashing"
    is_semantic = False

    def __init__(self, dimension: int = 512) -> None:
        if dimension < 16:
            raise ValueError("dimension must be at least 16")
        self.dimension = dimension
        self.name = f"hashing-v{HASHING_VERSION}-d{dimension}"

    def _features(self, text: str) -> dict[str, float]:
        words = [w for w in _TOKEN.findall(text.lower()) if w not in _STOPWORDS]
        features: dict[str, float] = {}

        def add(key: str, weight: float) -> None:
            features[key] = features.get(key, 0.0) + weight

        for word in words:
            add("w:" + word, _WORD_WEIGHT)
            padded = f"<{word}>"
            if len(word) >= 4:
                for n in _CHAR_NGRAMS:
                    for i in range(len(padded) - n + 1):
                        add(f"c{n}:" + padded[i:i + n], _CHAR_WEIGHT)
        for left, right in zip(words, words[1:]):
            add(f"b:{left}_{right}", _BIGRAM_WEIGHT)
        return features

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for feature, weight in self._features(text).items():
                index, sign = _bucket(feature, self.dimension)
                matrix[row, index] += sign * (1.0 + math.log(weight)) if weight > 1.0 else sign * weight
        return _normalise_rows(matrix)


class SentenceTransformerEmbedder:
    backend = "sentence-transformers"
    is_semantic = True

    def __init__(self, model: str, local_files_only: bool = False, batch_size: int = 64) -> None:
        self.model_id = model
        self.batch_size = batch_size
        self.name = model
        try:
            from sentence_transformers import SentenceTransformer  # optional dependency
        except ImportError as exc:
            raise EmbeddingUnavailableError(
                "The sentence-transformers package is not installed. Run `pip install -r requirements-embeddings.txt` "
                "in backend/, or set EMBEDDING_BACKEND=hashing (lexical matching only)."
            ) from exc
        try:
            self._model = SentenceTransformer(model, local_files_only=local_files_only)
        except Exception as exc:  # network down, unknown model, corrupt cache ...
            logger.warning("Could not load embedding model %r (%s)", model, type(exc).__name__)
            raise EmbeddingUnavailableError(
                f"The embedding model '{model}' could not be loaded ({type(exc).__name__}). It is downloaded once "
                "from the Hugging Face hub: check the network connection, or point EMBEDDING_MODEL at a local model "
                "folder (and set EMBEDDING_LOCAL_FILES_ONLY=true to forbid downloads)."
            ) from exc
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts, batch_size=self.batch_size, convert_to_numpy=True,
                                     normalize_embeddings=False, show_progress_bar=False)
        return _normalise_rows(np.asarray(vectors, dtype=np.float32))


@lru_cache(maxsize=4)
def get_embedder(config: EmbedderConfig) -> Embedder:
    """Create (and cache) the embedder for a configuration. Raises EmbeddingUnavailableError with a fix hint."""
    if config.backend == "hashing":
        return HashingEmbedder(config.dimension)
    if config.backend == "sentence-transformers":
        return SentenceTransformerEmbedder(config.model, config.local_files_only, config.batch_size)
    raise EmbeddingUnavailableError(f"Unknown embedding backend '{config.backend}'.")
