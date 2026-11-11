"""Transparent score fusion.

    final_score = w_semantic * semantic + w_keyword * keyword + w_entity * entity
                + w_temporal * temporal + w_confidence * confidence + w_source * source

Every component is in [0, 1] and is returned with its weight and contribution, so a rank can always be explained.
Components (all documented in docs/retrieval.md):

semantic    cosine similarity of query and evidence text, clipped at 0 (from the Phase 6 vector index)
keyword     BM25 over the evidence text, divided by the best BM25 among the candidates (so the best = 1)
entity      1.0 when the evidence's canonical entity name is a clinical entity named in the query (via the lexicon,
            synonyms and abbreviations resolved); 0.5 when it contains all words of one; else 0
temporal    only when the query has a date/period or a recency word: 1 inside the period, decaying outside;
            "latest"/"earliest" rank dated items among the entity-matched candidates; undated items score 0
confidence  the extraction confidence (a heuristic score, not a probability)
source      OCR text is scaled by Tesseract's own mean confidence (0-1); text-layer/table = 1; a "page N" hint
            keeps matching pages at 1 and halves other pages

Weights are configuration, not truth: see docs/evaluation-retrieval.md for how the defaults were chosen and what
that evidence is worth.
"""

from dataclasses import asdict, dataclass, field
from datetime import date

from hybrid_retrieval.query import QueryAnalysis

COMPONENTS = ("semantic", "keyword", "entity", "temporal", "confidence", "source")
FORMULA = "final_score = " + " + ".join(f"w_{c} * {c}" for c in COMPONENTS)
_OUTSIDE_PERIOD_CAP = 0.5
_DECAY_DAYS = 30.0


@dataclass(frozen=True)
class Weights:
    semantic: float = 1.0
    keyword: float = 1.0
    entity: float = 1.0
    temporal: float = 1.0
    confidence: float = 0.1
    source: float = 0.1

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value < 0:
                raise ValueError(f"weight {name} must be >= 0")

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    @property
    def total(self) -> float:
        return sum(asdict(self).values())

    @classmethod
    def only(cls, component: str) -> "Weights":
        return cls(**{c: (1.0 if c == component else 0.0) for c in COMPONENTS})


@dataclass(frozen=True)
class EvidenceFeatures:
    """What ranking needs to know about one evidence item (no text, no vectors)."""
    id: str
    document_id: str
    page_number: int
    entity_name: str
    modality: str
    extraction_confidence: float
    date_iso: str | None = None
    ocr_confidence: float | None = None  # Tesseract mean word confidence, 0-100
    entity_type: str = ""
    assertion: str = "affirmed"
    order: tuple = ()  # stable position (document name, position in document): deterministic tie-break, independent of random ids


@dataclass
class ScoredItem:
    features: EvidenceFeatures
    components: dict[str, float]
    final_score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    temporal_note: str | None = None


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def entity_score(name: str, wanted: list[str]) -> float:
    if not wanted:
        return 0.0
    lowered = name.casefold()
    if any(lowered == w.casefold() for w in wanted):
        return 1.0
    words = set(lowered.split())
    return 0.5 if any(set(w.casefold().split()) <= words for w in wanted) else 0.0


def _period_score(iso: str | None, periods: list[tuple[str, str]]) -> tuple[float, str | None]:
    if not iso:
        return 0.0, "no date on this evidence"
    best_gap = None
    for start, end in periods:
        if start <= iso <= end:
            return 1.0, f"date {iso} is within the requested period"
        gap = min(_days(iso, start), _days(iso, end))
        best_gap = gap if best_gap is None else min(best_gap, gap)
    score = _OUTSIDE_PERIOD_CAP / (1.0 + (best_gap or 0) / _DECAY_DAYS)
    return score, f"date {iso} is {best_gap} day(s) outside the requested period"


def score_components(
    analysis: QueryAnalysis,
    items: list[EvidenceFeatures],
    semantic: dict[str, float],
    keyword_raw: dict[str, float],
    matched_terms: dict[str, list[str]] | None = None,
) -> list[ScoredItem]:
    """Compute all component scores for the candidate items. `semantic` = cosine per id, `keyword_raw` = BM25 per id."""
    top_keyword = max(keyword_raw.values(), default=0.0)
    entity = {i.id: entity_score(i.entity_name, analysis.entities) for i in items}

    # recency reference: dated items that match the named entity (or all dated items when none is named)
    recency: dict[str, float] = {}
    if analysis.recency:
        pool = [i for i in items if i.date_iso and (not analysis.entities or entity[i.id] > 0)]
        if pool:
            ordinals = {i.id: date.fromisoformat(i.date_iso).toordinal() for i in pool}
            lo, hi = min(ordinals.values()), max(ordinals.values())
            for i in pool:
                x = 1.0 if hi == lo else (ordinals[i.id] - lo) / (hi - lo)
                recency[i.id] = x if analysis.recency == "latest" else 1.0 - x

    scored: list[ScoredItem] = []
    for i in items:
        note = None
        if analysis.periods:
            temporal, note = _period_score(i.date_iso, analysis.periods)
        elif analysis.recency:
            temporal = recency.get(i.id, 0.0)
            note = (f"{analysis.recency} among the matching dated evidence" if i.id in recency
                    else "not in the dated, entity-matched pool")
        else:
            temporal = 0.0
        quality = (min(max(i.ocr_confidence, 0.0), 100.0) / 100.0) if i.modality in ("ocr", "image_ocr") and i.ocr_confidence is not None else 1.0
        if analysis.page_hint is not None and i.page_number != analysis.page_hint:
            quality *= 0.5
        scored.append(ScoredItem(
            features=i,
            components={
                "semantic": max(0.0, min(1.0, semantic.get(i.id, 0.0))),
                "keyword": (keyword_raw.get(i.id, 0.0) / top_keyword) if top_keyword > 0 else 0.0,
                "entity": entity[i.id],
                "temporal": temporal,
                "confidence": max(0.0, min(1.0, i.extraction_confidence)),
                "source": quality,
            },
            matched_terms=(matched_terms or {}).get(i.id, []),
            temporal_note=note,
        ))
    return scored


def fuse(item: ScoredItem, weights: Weights) -> float:
    w = weights.as_dict()
    return sum(w[c] * item.components[c] for c in COMPONENTS)


def rank(scored: list[ScoredItem], weights: Weights) -> list[ScoredItem]:
    """Sort by fused score. Ties: higher entity, higher keyword, then document name and position in the document
    (never a random id), so the same corpus always ranks identically. Sets `final_score`."""
    for item in scored:
        item.final_score = fuse(item, weights)
    return sorted(scored, key=lambda s: (-s.final_score, -s.components["entity"], -s.components["keyword"], s.features.order, s.features.id))
