"""Benchmark file format and relevance resolution.

queries.json:  {"queries": [{"id", "split": "dev"|"test", "category", "text", "judgments": [Judgment...]}]}
A judgment names evidence by its document file name and optional entity_name / entity_type / date_iso / value_text /
assertion. An evidence item is relevant to a query if it satisfies ANY of its judgments (all given fields equal).
Judgments are written by hand from the synthetic documents' text, never from system output. A judgment that matches
no extracted evidence is reported as unresolved (an extraction miss), and a query with no resolvable judgment is not scored.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Judgment:
    document: str
    entity_name: str | None = None
    entity_type: str | None = None
    date_iso: str | None = None
    value_text: str | None = None
    assertion: str | None = None


@dataclass(frozen=True)
class Query:
    id: str
    split: str
    category: str
    text: str
    judgments: tuple[Judgment, ...]


def load_queries(path: Path) -> list[Query]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = [
        Query(q["id"], q["split"], q["category"], q["text"], tuple(Judgment(**j) for j in q["judgments"]))
        for q in raw["queries"]
    ]
    ids = [q.id for q in queries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate query ids")
    for q in queries:
        if q.split not in ("dev", "test"):
            raise ValueError(f"{q.id}: split must be dev or test")
        if not q.judgments:
            raise ValueError(f"{q.id}: no judgments")
    return queries


def matches(judgment: Judgment, item: Mapping) -> bool:
    """`item` has document_filename, entity_name, entity_type, date_iso, value_text, assertion."""
    if item["document_filename"] != judgment.document:
        return False
    for field in ("entity_name", "entity_type", "date_iso", "value_text", "assertion"):
        wanted = getattr(judgment, field)
        if wanted is not None and item.get(field) != wanted:
            return False
    return True


def resolve_relevant(query: Query, items: Iterable[Mapping]) -> tuple[set[str], list[Judgment]]:
    """(ids of relevant evidence, judgments that matched nothing)."""
    items = list(items)
    relevant: set[str] = set()
    unresolved: list[Judgment] = []
    for judgment in query.judgments:
        hit = [i["evidence_id"] for i in items if matches(judgment, i)]
        relevant.update(hit)
        if not hit:
            unresolved.append(judgment)
    return relevant, unresolved
