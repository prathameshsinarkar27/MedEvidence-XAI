class EmbeddingUnavailableError(RuntimeError):
    """The configured embedding backend cannot be used (missing package, model not downloadable, ...).

    The message is safe to show to the user and says how to fix it."""


class VectorBackendUnavailableError(RuntimeError):
    """The configured vector search backend cannot be used (e.g. faiss is not installed)."""
