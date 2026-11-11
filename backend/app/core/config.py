"""Application configuration.

All settings come from environment variables (optionally loaded from a `.env`
file in the repository root). No secrets or credentials are hard-coded.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from document_processing import ProcessingConfig  # repo root is put on sys.path by app/__init__.py
from evidence_index import EmbedderConfig
from evidence_reasoning import ReasoningConfig, VerifyWeights
from hybrid_retrieval import Weights

# backend/app/core/config.py -> repository root is three levels above `app/`
REPO_ROOT = Path(__file__).resolve().parents[3]

RESEARCH_DISCLAIMER = (
    "This is a research/educational prototype and is not a substitute for "
    "professional medical diagnosis or treatment."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MedEvidence-XAI"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_dir: str = "logs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:PASSWORD@host:5432/dbname
    # Intentionally has no default: credentials must come from the environment.
    database_url: str | None = Field(default=None)

    # Phase 2: document upload. Files are stored under UPLOAD_DIR (relative paths
    # are resolved against the repository root).
    upload_dir: str = "data/uploads"
    max_upload_size_mb: int = Field(default=25, ge=1, le=200)

    # Phase 3: PDF text extraction + OCR.
    tesseract_cmd: str | None = None  # full path to the tesseract binary if it is not on PATH
    ocr_languages: str = "eng"  # Tesseract codes joined with "+", e.g. "eng+hin"
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    ocr_timeout_seconds: int = Field(default=60, ge=5, le=600)
    min_text_chars_per_page: int = Field(default=25, ge=1, le=1000)
    max_pdf_pages: int = Field(default=300, ge=1, le=2000)

    # Phase 4: tables and embedded images. Extracted images are written under IMAGE_DIR (relative paths
    # resolve against the repository root). The default location is git-ignored.
    image_dir: str = "data/images"
    auto_multimodal: bool = True  # run table/image extraction automatically after text processing
    image_ocr: bool = False  # OCR text printed inside extracted images (needs Tesseract)
    min_image_side_px: int = Field(default=32, ge=1, le=2000)
    max_images_per_document: int = Field(default=200, ge=1, le=5000)
    max_tables_per_document: int = Field(default=500, ge=1, le=5000)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)
    max_image_pixels: int = Field(default=50_000_000, ge=1000, le=500_000_000)
    max_cells_per_table: int = Field(default=5000, ge=4, le=100_000)
    image_ocr_min_chars: int = Field(default=10, ge=1, le=1000)

    # Phase 5: clinical information extraction.
    auto_clinical_extraction: bool = True  # run automatically after text (and table/image) processing
    max_evidence_per_document: int = Field(default=20000, ge=10, le=500_000)

    # Phase 6: evidence index + semantic retrieval.
    # `hashing` needs no download but matches words/spellings only (NOT meaning). `sentence-transformers` is the real
    # semantic model: install requirements-embeddings.txt first (the model is downloaded once).
    embedding_backend: Literal["hashing", "sentence-transformers"] = "hashing"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = Field(default=512, ge=16, le=4096)  # hashing backend only
    embedding_local_files_only: bool = False  # never touch the network when loading the model
    embedding_batch_size: int = Field(default=64, ge=1, le=1024)
    vector_backend: Literal["faiss", "numpy"] = "faiss"
    auto_index_evidence: bool = True  # index a document's evidence automatically after clinical extraction
    search_max_top_k: int = Field(default=100, ge=1, le=1000)

    # Phase 7: hybrid ranking. final_score = sum(weight * component); see docs/retrieval.md and
    # docs/evaluation-retrieval.md. The defaults were chosen on the dev split of a small synthetic benchmark with the
    # lexical (hashing) embedding: re-tune (scripts/evaluate_retrieval.py) after switching embedding. All weights >= 0.
    rank_weight_semantic: float = Field(default=0.85, ge=0, le=100)
    rank_weight_keyword: float = Field(default=0.0, ge=0, le=100)
    rank_weight_entity: float = Field(default=1.21, ge=0, le=100)
    rank_weight_temporal: float = Field(default=1.38, ge=0, le=100)
    rank_weight_confidence: float = Field(default=0.0, ge=0, le=100)
    rank_weight_source: float = Field(default=0.05, ge=0, le=100)
    ranking_candidate_pool: int = Field(default=100, ge=10, le=5000)  # semantic candidates considered per query

    # Phase 8: evidence verification and conflict detection. evidence_score = weighted mean of the applicable components.
    # All values are engineering defaults chosen by reasoning, NOT tuned or calibrated on data ("Not yet evaluated").
    verify_weight_relevance: float = Field(default=1.0, ge=0, le=100)
    verify_weight_entity: float = Field(default=1.5, ge=0, le=100)
    verify_weight_value: float = Field(default=0.5, ge=0, le=100)
    verify_weight_temporal: float = Field(default=1.0, ge=0, le=100)
    verify_weight_confidence: float = Field(default=0.75, ge=0, le=100)
    verify_weight_source: float = Field(default=0.75, ge=0, le=100)
    verify_weight_directness: float = Field(default=2.0, ge=0, le=100)
    verify_weight_agreement: float = Field(default=0.5, ge=0, le=100)
    verify_supported_score: float = Field(default=0.70, ge=0, le=1)  # evidence_score for an item to count as supporting
    verify_min_relevant_score: float = Field(default=0.35, ge=0, le=1)  # below this an item is excluded
    verify_min_semantic_no_entity: float = Field(default=0.30, ge=0, le=1)
    verify_undated_temporal_score: float = Field(default=0.25, ge=0, le=1)
    verify_candidates: int = Field(default=30, ge=1, le=1000)  # evidence items retrieved per question
    # Largest relative difference still called "measurement variation" (same or unknown time). Not clinical thresholds.
    conflict_tolerance_lab: float = Field(default=0.05, ge=0, le=1)
    conflict_tolerance_vital: float = Field(default=0.10, ge=0, le=1)
    conflict_tolerance_medication: float = Field(default=0.0, ge=0, le=1)
    conflict_tolerance_default: float = Field(default=0.05, ge=0, le=1)

    @field_validator("ocr_languages")
    @classmethod
    def _validate_ocr_languages(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*", value):
            raise ValueError("OCR_LANGUAGES must look like 'eng' or 'eng+hin'")
        return value

    @field_validator("tesseract_cmd")
    @classmethod
    def _blank_tesseract_cmd_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid LOG_LEVEL: {value!r}")
        return level

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def processing_config(self) -> ProcessingConfig:
        return ProcessingConfig(
            min_text_chars=self.min_text_chars_per_page,
            ocr_languages=self.ocr_languages,
            ocr_dpi=self.ocr_dpi,
            ocr_timeout_seconds=self.ocr_timeout_seconds,
            max_pages=self.max_pdf_pages,
            tesseract_cmd=self.tesseract_cmd,
            min_image_side_px=self.min_image_side_px,
            max_images_per_document=self.max_images_per_document,
            max_tables_per_document=self.max_tables_per_document,
            max_image_bytes=self.max_image_bytes,
            max_image_pixels=self.max_image_pixels,
            max_cells_per_table=self.max_cells_per_table,
            image_ocr=self.image_ocr,
            image_ocr_min_chars=self.image_ocr_min_chars,
        )

    @property
    def embedder_config(self) -> EmbedderConfig:
        return EmbedderConfig(
            backend=self.embedding_backend,
            model=self.embedding_model.strip(),
            dimension=self.embedding_dimension,
            local_files_only=self.embedding_local_files_only,
            batch_size=self.embedding_batch_size,
        )

    @property
    def rank_weights(self) -> Weights:
        return Weights(
            semantic=self.rank_weight_semantic, keyword=self.rank_weight_keyword, entity=self.rank_weight_entity,
            temporal=self.rank_weight_temporal, confidence=self.rank_weight_confidence, source=self.rank_weight_source,
        )

    @property
    def reasoning_config(self) -> ReasoningConfig:
        return ReasoningConfig(
            weights=VerifyWeights(
                relevance=self.verify_weight_relevance, entity=self.verify_weight_entity, value=self.verify_weight_value,
                temporal=self.verify_weight_temporal, confidence=self.verify_weight_confidence, source=self.verify_weight_source,
                directness=self.verify_weight_directness, agreement=self.verify_weight_agreement),
            supported_score=self.verify_supported_score, min_relevant_score=self.verify_min_relevant_score,
            min_semantic_no_entity=self.verify_min_semantic_no_entity, undated_temporal_score=self.verify_undated_temporal_score,
            tolerance_lab=self.conflict_tolerance_lab, tolerance_vital=self.conflict_tolerance_vital,
            tolerance_medication=self.conflict_tolerance_medication, tolerance_default=self.conflict_tolerance_default)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_dir_path(self) -> Path:
        path = Path(self.upload_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def image_dir_path(self) -> Path:
        path = Path(self.image_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def log_dir_path(self) -> Path | None:
        if not self.log_dir:
            return None
        path = Path(self.log_dir)
        return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
