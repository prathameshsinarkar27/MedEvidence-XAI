from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

PHASE2_DOCUMENT_COLUMNS = {
    "id", "original_filename", "stored_filename", "file_type", "mime_type",
    "file_size_bytes", "sha256", "storage_path", "upload_status", "uploaded_at",
}
PHASE3_DOCUMENT_COLUMNS = {
    "page_count", "processing_status", "processing_error_code", "processing_error", "processed_at", "pdf_metadata",
}
PHASE4_DOCUMENT_COLUMNS = {
    "multimodal_status", "multimodal_error_code", "multimodal_error", "multimodal_processed_at",
    "multimodal_page_count", "multimodal_pages_processed", "table_count", "image_count", "multimodal_summary",
}
PHASE5_DOCUMENT_COLUMNS = {
    "clinical_status", "clinical_error_code", "clinical_error", "clinical_processed_at", "clinical_page_count",
    "clinical_pages_processed", "evidence_count", "clinical_summary",
}
PHASE6_DOCUMENT_COLUMNS = {"index_status", "index_error_code", "index_error", "indexed_at", "indexed_count", "index_model"}
EMBEDDING_COLUMNS = {
    "evidence_id", "document_id", "model_name", "backend", "text_version", "dimension", "embedding_text",
    "text_sha256", "vector", "created_at",
}
EVIDENCE_COLUMNS = {
    "id", "document_id", "page_number", "ordinal", "modality", "entity_type", "entity_name", "assertion",
    "mention_text", "source_text", "source_field", "char_start", "char_end", "source_start", "source_end",
    "value_text", "value_numeric", "value_comparator", "unit_text", "unit_normalized", "reference_text",
    "reference_low", "reference_high", "abnormal_flag", "flag_source", "date_text", "date_iso", "attributes",
    "table_id", "table_row_index", "cell_positions", "image_id", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1",
    "page_width", "page_height", "page_rotation", "extraction_method", "extractor_version",
    "extraction_confidence", "confidence_factors", "ocr_confidence", "created_at",
}
TABLE_COLUMNS = {
    "id", "document_id", "page_number", "table_index", "detection_method", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1",
    "page_width", "page_height", "page_rotation", "row_count", "col_count", "created_at",
}
CELL_COLUMNS = {"id", "table_id", "row_index", "col_index", "text", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"}
IMAGE_COLUMNS = {
    "id", "document_id", "page_number", "image_index", "xref", "width_px", "height_px", "colorspace",
    "bits_per_component", "original_format", "stored_format", "stored_filename", "file_size_bytes", "sha256",
    "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1", "page_width", "page_height", "page_rotation", "is_full_page",
    "extraction_status", "error_message", "ocr_status", "ocr_text", "ocr_mean_confidence", "created_at",
}
PAGE_COLUMNS = {
    "id", "document_id", "page_number", "extraction_method", "extracted_text", "char_count",
    "processing_status", "ocr_status", "ocr_mean_confidence", "has_images", "is_likely_scanned",
    "error_message", "created_at",
}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_single_linear_migration_head():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == ["0006"]
    assert [r.revision for r in script.walk_revisions()] == ["0006", "0005", "0004", "0003", "0002", "0001"]


@pytest.mark.integration
def test_upgrade_and_downgrade_roundtrip(set_database_url, test_database_url):
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)

    def phase() -> str:
        with engine.connect() as conn:
            return conn.execute(text("SELECT value FROM app_metadata WHERE key='schema_phase'")).scalar_one()

    def columns(table: str) -> set[str]:
        return {c["name"] for c in inspect(engine).get_columns(table)}

    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        assert {"app_metadata", "documents", "document_pages"} <= set(inspect(engine).get_table_names())
        assert phase() == "6"
        assert columns("documents") == (
            PHASE2_DOCUMENT_COLUMNS | PHASE3_DOCUMENT_COLUMNS | PHASE4_DOCUMENT_COLUMNS | PHASE5_DOCUMENT_COLUMNS
            | PHASE6_DOCUMENT_COLUMNS
        )
        assert columns("evidence_embeddings") == EMBEDDING_COLUMNS
        embedding_fks = {fk["constrained_columns"][0]: (fk["referred_table"], fk["options"].get("ondelete", "").upper())
                         for fk in inspect(engine).get_foreign_keys("evidence_embeddings")}
        assert embedding_fks == {"evidence_id": ("clinical_evidence", "CASCADE"), "document_id": ("documents", "CASCADE")}
        assert columns("clinical_evidence") == EVIDENCE_COLUMNS
        evidence_fks = {fk["constrained_columns"][0]: (fk["referred_table"], fk["options"].get("ondelete", "").upper())
                        for fk in inspect(engine).get_foreign_keys("clinical_evidence")}
        assert evidence_fks == {"document_id": ("documents", "CASCADE"), "table_id": ("document_tables", "SET NULL"),
                                "image_id": ("document_images", "SET NULL")}
        assert columns("document_pages") == PAGE_COLUMNS
        assert columns("document_tables") == TABLE_COLUMNS
        assert columns("table_cells") == CELL_COLUMNS
        assert columns("document_images") == IMAGE_COLUMNS
        for table, parent in (("document_pages", "documents"), ("document_tables", "documents"),
                              ("document_images", "documents"), ("table_cells", "document_tables")):
            foreign_keys = inspect(engine).get_foreign_keys(table)
            assert foreign_keys[0]["referred_table"] == parent
            assert foreign_keys[0]["options"].get("ondelete", "").upper() == "CASCADE"

        command.downgrade(cfg, "0005")  # Phase 6 can be reverted without losing Phase 5
        assert "evidence_embeddings" not in inspect(engine).get_table_names() and "clinical_evidence" in inspect(engine).get_table_names()
        assert columns("documents") == (
            PHASE2_DOCUMENT_COLUMNS | PHASE3_DOCUMENT_COLUMNS | PHASE4_DOCUMENT_COLUMNS | PHASE5_DOCUMENT_COLUMNS)
        assert phase() == "5"
        command.upgrade(cfg, "head")

        command.downgrade(cfg, "0004")  # Phase 5 can be reverted without losing Phase 4
        assert "clinical_evidence" not in inspect(engine).get_table_names() and "document_tables" in inspect(engine).get_table_names()
        assert columns("documents") == PHASE2_DOCUMENT_COLUMNS | PHASE3_DOCUMENT_COLUMNS | PHASE4_DOCUMENT_COLUMNS
        assert phase() == "4"
        command.upgrade(cfg, "head")

        command.downgrade(cfg, "0003")  # Phase 4 can be reverted without losing Phase 3
        tables = set(inspect(engine).get_table_names())
        assert not ({"document_tables", "table_cells", "document_images"} & tables) and "document_pages" in tables
        assert columns("documents") == PHASE2_DOCUMENT_COLUMNS | PHASE3_DOCUMENT_COLUMNS
        assert phase() == "3"
        command.upgrade(cfg, "head")

        command.downgrade(cfg, "0002")  # Phase 3 can be reverted without losing Phase 2
        assert "document_pages" not in inspect(engine).get_table_names()
        assert columns("documents") == PHASE2_DOCUMENT_COLUMNS
        assert phase() == "2"

        command.downgrade(cfg, "0001")
        assert "documents" not in inspect(engine).get_table_names() and phase() == "1"

        command.downgrade(cfg, "base")
        assert "app_metadata" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")  # leave the test DB migrated
    finally:
        engine.dispose()


@pytest.mark.integration
def test_existing_phase2_rows_survive_upgrade_with_defaults(set_database_url, test_database_url):
    """A Phase 2 database (documents already uploaded) must upgrade cleanly."""
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "0002")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO documents (id, original_filename, stored_filename, file_type, mime_type, "
                    "file_size_bytes, sha256, storage_path, upload_status, uploaded_at) VALUES "
                    "('11111111-1111-1111-1111-111111111111', 'old.pdf', 'old.pdf', 'pdf', 'application/pdf', "
                    "10, 'abc', 'old.pdf', 'uploaded', now())"
                )
            )
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT processing_status, page_count, multimodal_status, multimodal_pages_processed, table_count, "
                     "clinical_status, clinical_pages_processed, evidence_count "
                     "FROM documents")
            ).one()
        assert tuple(row) == ("not_processed", None, "not_processed", 0, None, "not_processed", 0, None)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM documents"))
        engine.dispose()
