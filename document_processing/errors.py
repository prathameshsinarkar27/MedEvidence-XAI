"""Exceptions carrying a stable machine-readable `code` and a human-readable `message`."""


class DocumentProcessingError(Exception):
    code = "processing_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class PdfOpenError(DocumentProcessingError):
    """The PDF cannot be processed at all (corrupt, encrypted, empty, too many pages)."""

    code = "invalid_pdf"


class OcrUnavailableError(DocumentProcessingError):
    """Tesseract is missing or misconfigured. The message tells the operator how to fix it."""

    code = "ocr_unavailable"


class OcrFailedError(DocumentProcessingError):
    """OCR ran but failed for one page (timeout, unreadable image, ...)."""

    code = "ocr_failed"
