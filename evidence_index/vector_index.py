"""Exact nearest-neighbour search over L2-normalised vectors (cosine similarity = inner product).

Two interchangeable implementations: FAISS (`IndexFlatIP`, exact) and NumPy (exact, no extra dependency).
Both return identical rankings up to floating-point ties. The index stores only opaque ids; provenance is
resolved by the caller. An optional `allowed` set restricts the search *before* ranking (pre-filtering), so
filtered searches still return up to k results.
"""

from dataclasses import dataclass
from typing import Collection, Protocol

import numpy as np

from evidence_index.errors import VectorBackendUnavailableError


@dataclass(frozen=True)
class ScoredId:
    id: str
    score: float  # cosine similarity in [-1, 1]


class VectorIndex(Protocol):
    backend: str

    def __len__(self) -> int: ...
    def search(self, query: np.ndarray, k: int, allowed: Collection[str] | None = None) -> list[ScoredId]: ...


def _check(ids: list[str], vectors: np.ndarray) -> np.ndarray:
    matrix = np.ascontiguousarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(ids):
        raise ValueError("vectors must be a 2-D array with one row per id")
    return matrix


class NumpyIndex:
    backend = "numpy"

    def __init__(self, ids: list[str], vectors: np.ndarray) -> None:
        self._ids = list(ids)
        self._matrix = _check(ids, vectors)
        self._position = {id_: i for i, id_ in enumerate(self._ids)}

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: np.ndarray, k: int, allowed: Collection[str] | None = None) -> list[ScoredId]:
        if not self._ids or k <= 0:
            return []
        scores = self._matrix @ np.asarray(query, dtype=np.float32).reshape(-1)
        if allowed is not None:
            positions = np.fromiter((self._position[a] for a in allowed if a in self._position), dtype=np.int64)
            if positions.size == 0:
                return []
        else:
            positions = np.arange(len(self._ids))
        order = positions[np.argsort(-scores[positions], kind="stable")][:k]
        return [ScoredId(self._ids[i], float(scores[i])) for i in order]


class FaissIndex:
    backend = "faiss"

    def __init__(self, ids: list[str], vectors: np.ndarray) -> None:
        try:
            import faiss  # type: ignore
        except ImportError as exc:
            raise VectorBackendUnavailableError(
                "faiss is not installed. Run `pip install faiss-cpu`, or set VECTOR_BACKEND=numpy."
            ) from exc
        self._faiss = faiss
        self._ids = list(ids)
        matrix = _check(ids, vectors)
        self._position = {id_: i for i, id_ in enumerate(self._ids)}
        dimension = matrix.shape[1] if matrix.size else 1
        self._index = faiss.IndexFlatIP(dimension)
        if len(self._ids):
            self._index.add(matrix)

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: np.ndarray, k: int, allowed: Collection[str] | None = None) -> list[ScoredId]:
        if not self._ids or k <= 0:
            return []
        q = np.ascontiguousarray(np.asarray(query, dtype=np.float32).reshape(1, -1))
        params = None
        limit = len(self._ids)
        if allowed is not None:
            positions = np.fromiter((self._position[a] for a in allowed if a in self._position), dtype=np.int64)
            if positions.size == 0:
                return []
            params = self._faiss.SearchParameters()
            params.sel = self._faiss.IDSelectorBatch(positions)
            limit = int(positions.size)
        scores, indices = self._index.search(q, min(k, limit), params=params)
        return [ScoredId(self._ids[i], float(s)) for s, i in zip(scores[0], indices[0]) if i >= 0]


def vector_backend_status(backend: str) -> tuple[bool, str | None]:
    """(available, message) for a configured backend name, without building an index."""
    if backend == "numpy":
        return True, None
    try:
        import faiss  # type: ignore  # noqa: F401
    except ImportError:
        return False, "faiss is not installed. Run `pip install faiss-cpu`, or set VECTOR_BACKEND=numpy."
    return True, None


def create_vector_index(backend: str, ids: list[str], vectors: np.ndarray) -> VectorIndex:
    if backend == "faiss":
        return FaissIndex(ids, vectors)
    if backend == "numpy":
        return NumpyIndex(ids, vectors)
    raise VectorBackendUnavailableError(f"Unknown vector backend '{backend}'.")
