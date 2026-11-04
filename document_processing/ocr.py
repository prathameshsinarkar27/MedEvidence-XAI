"""Tesseract OCR wrapper with explicit, actionable setup errors (never fails silently)."""

import io
import logging

import pytesseract
from PIL import Image
from pytesseract import Output, TesseractNotFoundError

from document_processing.errors import OcrFailedError, OcrUnavailableError
from document_processing.models import OcrResult, ProcessingConfig, TesseractStatus
from document_processing.text_extraction import clean_text

logger = logging.getLogger(__name__)

SETUP_HELP = (
    "Install Tesseract OCR and make sure the `tesseract` command is on PATH, or set TESSERACT_CMD in .env "
    "to its full path. Ubuntu/Debian: `sudo apt install tesseract-ocr`; macOS: `brew install tesseract`; "
    "Windows: install the UB Mannheim build and set TESSERACT_CMD (e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe)."
)


def _split_languages(languages: str) -> list[str]:
    return [lang for lang in languages.split("+") if lang]


def _apply_cmd(config: ProcessingConfig) -> None:
    pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd or "tesseract"


def check_tesseract(config: ProcessingConfig) -> TesseractStatus:
    """Probe Tesseract and the requested language data. Never raises."""
    requested = _split_languages(config.ocr_languages)
    _apply_cmd(config)
    try:
        version = str(pytesseract.get_tesseract_version())
    except (TesseractNotFoundError, FileNotFoundError, PermissionError, OSError):
        return TesseractStatus(
            available=False,
            requested_languages=requested,
            message=f"Tesseract OCR was not found. {SETUP_HELP}",
        )
    except Exception as exc:
        return TesseractStatus(
            available=False,
            requested_languages=requested,
            message=f"Tesseract could not be run ({type(exc).__name__}). {SETUP_HELP}",
        )

    try:
        installed = sorted(pytesseract.get_languages(config=""))
    except Exception:
        installed = []
    missing = [lang for lang in requested if lang not in installed]
    if missing:
        return TesseractStatus(
            available=False,
            version=version,
            requested_languages=requested,
            installed_languages=installed,
            missing_languages=missing,
            message=(
                f"Tesseract {version} is installed but language data is missing for: {', '.join(missing)}. "
                f"Install the matching tesseract-ocr-<lang> package (or traineddata files) or change OCR_LANGUAGES "
                f"in .env. Installed languages: {', '.join(installed) or 'unknown'}."
            ),
        )
    return TesseractStatus(
        available=True,
        version=version,
        requested_languages=requested,
        installed_languages=installed,
    )


class TesseractOcr:
    """OCR engine. The availability check runs once and is cached for the lifetime of the object."""

    def __init__(self, config: ProcessingConfig) -> None:
        self._config = config
        self._status: TesseractStatus | None = None

    @property
    def status(self) -> TesseractStatus:
        if self._status is None:
            self._status = check_tesseract(self._config)
        return self._status

    def ensure_available(self) -> None:
        status = self.status
        if not status.available:
            raise OcrUnavailableError(status.message or SETUP_HELP)

    def recognize_png(self, png_bytes: bytes) -> OcrResult:
        """Run OCR on a PNG image. Raises OcrUnavailableError or OcrFailedError."""
        self.ensure_available()
        _apply_cmd(self._config)
        try:
            with Image.open(io.BytesIO(png_bytes)) as image:
                image.load()
                data = pytesseract.image_to_data(
                    image,
                    lang=self._config.ocr_languages,
                    output_type=Output.DICT,
                    timeout=self._config.ocr_timeout_seconds,
                )
        except TesseractNotFoundError as exc:
            raise OcrUnavailableError(f"Tesseract OCR was not found. {SETUP_HELP}") from exc
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise OcrFailedError(f"OCR timed out or failed: {str(exc)[:200]}") from exc
        except Exception as exc:
            raise OcrFailedError(f"OCR failed ({type(exc).__name__}).") from exc
        return _assemble(data)


def _assemble(data: dict) -> OcrResult:
    """Rebuild text from Tesseract's word table: words on a line joined by spaces, lines by \\n,
    paragraphs/blocks separated by a blank line. Mean confidence is over recognised words."""
    lines: list[tuple[tuple[int, int], list[str]]] = []
    current_key: tuple[int, int, int] | None = None
    confidences: list[float] = []

    for i, raw in enumerate(data.get("text", [])):
        word = (raw or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf >= 0:
            confidences.append(conf)
        if key != current_key:
            lines.append(((key[0], key[1]), [word]))
            current_key = key
        else:
            lines[-1][1].append(word)

    out: list[str] = []
    previous_para: tuple[int, int] | None = None
    for para, words in lines:
        if previous_para is not None and para != previous_para:
            out.append("")
        out.append(" ".join(words))
        previous_para = para

    mean = round(sum(confidences) / len(confidences), 1) if confidences else None
    return OcrResult(text=clean_text("\n".join(out)), mean_confidence=mean)
