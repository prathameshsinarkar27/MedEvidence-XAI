"""Stand-ins for TesseractOcr so most tests are deterministic and need no Tesseract install."""

from document_processing.errors import OcrFailedError, OcrUnavailableError
from document_processing.models import OcrResult


class StubOcr:
    def __init__(self, text: str = "OCR TEXT FROM STUB", confidence: float | None = 91.5) -> None:
        self._result = OcrResult(text=text, mean_confidence=confidence)
        self.calls = 0

    def recognize_png(self, png_bytes: bytes) -> OcrResult:
        assert png_bytes.startswith(b"\x89PNG"), "OCR must receive a PNG"
        self.calls += 1
        return self._result


class UnavailableOcr:
    def __init__(self, message: str = "Tesseract OCR was not found. Install it.") -> None:
        self._message = message
        self.calls = 0

    def recognize_png(self, png_bytes: bytes) -> OcrResult:
        self.calls += 1
        raise OcrUnavailableError(self._message)


class FailingOcr:
    def recognize_png(self, png_bytes: bytes) -> OcrResult:
        raise OcrFailedError("OCR timed out or failed: simulated")
