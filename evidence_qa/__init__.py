"""Evidence-grounded answer generation (Phase 9).

A pure library (no database, no web framework). Input: the verified evidence context from Phase 8. Output: an answer in which
every claim cites evidence, or an abstention; a confidence report that keeps model confidence, evidence confidence and answer
support apart; and the reasons evidence was selected. The default provider is deterministic and offline; an optional
OpenAI-compatible provider (local open-source server or external API) can draft the wording, but its output is validated by a
grounding guard and replaced by the extractive answer when it leaves the evidence. See docs/explainability.md.
"""

from evidence_qa.explain import selection_reasons
from evidence_qa.extractive import compose, describe, value_with_unit
from evidence_qa.guard import validate
from evidence_qa.llm import OpenAICompatibleProvider, ProviderError, build_messages, is_local_url, parse_response
from evidence_qa.pipeline import build_answer
from evidence_qa.types import (
    ABSTAINED,
    ABSTENTION_MESSAGE,
    ANSWERED,
    ANSWERED_WITH_CAVEATS,
    CONFLICT_REPORTED,
    DISCLAIMER,
    STATUSES,
    AnswerContext,
    AnswerResult,
    Claim,
    ConfidenceReport,
    CtxConflict,
    CtxEvidence,
    Draft,
    Violation,
)

__all__ = [
    "ABSTAINED", "ABSTENTION_MESSAGE", "ANSWERED", "ANSWERED_WITH_CAVEATS", "CONFLICT_REPORTED", "DISCLAIMER", "STATUSES",
    "AnswerContext", "AnswerResult", "Claim", "ConfidenceReport", "CtxConflict", "CtxEvidence", "Draft", "OpenAICompatibleProvider",
    "ProviderError", "Violation", "build_answer", "build_messages", "compose", "describe", "is_local_url", "parse_response",
    "selection_reasons", "validate", "value_with_unit",
]
