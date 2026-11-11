"""Keyword matching: Okapi BM25 over evidence text. Pure Python, no dependency.

BM25 scores a document higher when it contains the query terms, more often, and when the terms are rare in the
corpus; long documents are mildly penalised. k1 and b are the standard defaults (1.5, 0.75), not tuned.
There is no stemming and no synonym expansion: "glucose" and "glucoses" are different tokens.
"""

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to was were with that this what which who when "
    "did does do has have had patient show shows".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class BM25Index:
    def __init__(self, documents: dict[str, str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._tf: dict[str, Counter] = {}
        self._len: dict[str, int] = {}
        df: Counter = Counter()
        for doc_id, text in documents.items():
            tokens = tokenize(text)
            counts = Counter(tokens)
            self._tf[doc_id] = counts
            self._len[doc_id] = len(tokens)
            df.update(counts.keys())
        self._n = len(documents)
        self._avg = (sum(self._len.values()) / self._n) if self._n else 0.0
        # BM25+ style non-negative idf
        self._idf = {t: math.log(1 + (self._n - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def __len__(self) -> int:
        return self._n

    def score(self, query_tokens: list[str], allowed: set[str] | None = None) -> dict[str, float]:
        """Raw BM25 score per document with a positive score (documents sharing no query term are omitted)."""
        terms = [t for t in dict.fromkeys(query_tokens) if t in self._idf]
        if not terms:
            return {}
        scores: dict[str, float] = {}
        for doc_id, tf in self._tf.items():
            if allowed is not None and doc_id not in allowed:
                continue
            total = 0.0
            norm = self.k1 * (1 - self.b + self.b * self._len[doc_id] / (self._avg or 1.0))
            for t in terms:
                f = tf.get(t)
                if f:
                    total += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if total > 0:
                scores[doc_id] = total
        return scores

    def matched_terms(self, query_tokens: list[str], doc_id: str) -> list[str]:
        tf = self._tf.get(doc_id, {})
        return [t for t in dict.fromkeys(query_tokens) if t in tf]
