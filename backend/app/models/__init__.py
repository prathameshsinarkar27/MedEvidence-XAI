"""ORM models. Import every model here so Alembic sees it via Base.metadata."""

from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import Document
from app.models.document_image import DocumentImage
from app.models.document_page import DocumentPage
from app.models.document_table import DocumentTable, TableCell
from app.models.evidence_embedding import EvidenceEmbedding

__all__ = [
    "ClinicalEvidence", "Document", "DocumentImage", "DocumentPage", "DocumentTable", "EvidenceEmbedding", "TableCell",
]
