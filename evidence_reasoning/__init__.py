"""Question understanding, evidence verification and conflict detection (Phase 8).

A pure library (no FastAPI, no database, no model, no text generation). Given a question and the evidence retrieved for it
(Phase 7), it produces: the question's structure, a transparent per-evidence verification score, a conflict analysis that
separates temporal change / measurement variation / possible contradiction, and an evidence state: supported, partially
supported, conflicting or insufficient evidence. It does NOT write answers (Phase 9). See docs/question-understanding.md,
docs/verification.md and docs/conflict-detection.md.
"""

from evidence_reasoning.conflicts import analyze_conflicts
from evidence_reasoning.pipeline import verify_question
from evidence_reasoning.question import understand_question
from evidence_reasoning.types import (
    CONFLICT_CATEGORIES,
    STATES,
    VERIFY_COMPONENTS,
    VERIFY_FORMULA,
    ConflictAnalysis,
    ConflictPair,
    EvidenceState,
    ItemVerification,
    QuestionAnalysis,
    ReasoningConfig,
    ValueConstraint,
    VEvidence,
    VerificationResult,
    VerifyWeights,
)

__all__ = [
    "CONFLICT_CATEGORIES", "STATES", "VERIFY_COMPONENTS", "VERIFY_FORMULA", "ConflictAnalysis", "ConflictPair", "EvidenceState",
    "ItemVerification", "QuestionAnalysis", "ReasoningConfig", "ValueConstraint", "VEvidence", "VerificationResult",
    "VerifyWeights", "analyze_conflicts", "understand_question", "verify_question",
]
