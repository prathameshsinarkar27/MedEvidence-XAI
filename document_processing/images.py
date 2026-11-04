"""Embedded image detection and extraction for one page.

For each image placement PyMuPDF reports (`Page.get_image_info(xrefs=True)`), the image object is extracted
from the PDF and stored as PNG or JPEG together with its metadata and its placement box. The content of an
image is NOT interpreted: no classification, no diagnosis, no analysis of medical images. The only optional
content step is OCR of text printed inside the image.

Format policy: baseline JPEG/PNG data is kept byte-for-byte; every other format (JPEG 2000, JBIG2, CMYK, indexed,
images with unusual encodings) is converted to RGB PNG so that a browser can show it. Soft masks (transparency)
are not applied.
"""

import hashlib
import io
import logging

import pymupdf
from PIL import Image

from document_processing.errors import OcrFailedError, OcrUnavailableError
from document_processing.models import (
    IMAGE_EXTRACTED,
    IMAGE_FAILED,
    IMG_OCR_COMPLETED,
    IMG_OCR_FAILED,
    IMG_OCR_NO_TEXT,
    IMG_OCR_NOT_REQUESTED,
    IMG_OCR_SKIPPED_PAGE_SCAN,
    IMG_OCR_UNAVAILABLE,
    BBox,
    ImageResult,
    PageMultimodalResult,
    ProcessingConfig,
)
from document_processing.page_view import unrotated
from document_processing.text_extraction import count_text_chars

logger = logging.getLogger(__name__)

_KEEP_AS_IS = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg"}


def _prepare_png_for_ocr(data: bytes, max_side: int) -> bytes:
    """Re-encode as PNG (the OCR contract) and downscale very large images."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        image = image.convert("L") if image.mode in ("L", "1", "P", "LA") else image.convert("RGB")
        longest = max(image.size)
        if longest > max_side:
            scale = max_side / longest
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()


def _extract_bytes(doc: pymupdf.Document, xref: int) -> tuple[bytes, str, str | None, int | None]:
    """Return (data, stored_format, original_format, colorspace_components_or_None); raises on failure."""
    raw = doc.extract_image(xref)
    if not raw or not raw.get("image"):
        raise ValueError("no image data")
    original = (raw.get("ext") or "").lower() or None
    components = raw.get("colorspace")
    if original in _KEEP_AS_IS and components in (1, 3):
        return raw["image"], _KEEP_AS_IS[original], original, components
    pix = pymupdf.Pixmap(doc, xref)
    try:
        if pix.colorspace is None or pix.colorspace.n != 3 or pix.alpha:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return pix.tobytes("png"), "png", original, components
    finally:
        pix = None  # noqa: F841  (release native memory promptly)


def _colorspace_name(info: dict) -> str | None:
    name = info.get("cs-name")
    return str(name)[:60] if name else None


def _box(value) -> BBox | None:
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _area(box: BBox) -> float:
    return max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)


def extract_images(
    doc: pymupdf.Document,
    page,
    page_number: int,
    config: ProcessingConfig,
    result: PageMultimodalResult,
    budget: int,
    ocr,
    image_ocr: bool,
) -> None:
    """Fill `result.images`. `budget` is how many more images may be stored for the whole document."""
    with unrotated(page) as (width, height, rotation):
        infos = page.get_image_info(xrefs=True)
        page_area = width * height
        index = 0
        for info in infos:
            w, h = int(info.get("width") or 0), int(info.get("height") or 0)
            if min(w, h) < config.min_image_side_px:
                result.images_skipped_small += 1
                continue
            if budget - len(result.images) <= 0:
                result.images_skipped_over_limit += 1
                continue

            index += 1
            bbox = _box(info.get("bbox"))
            xref = int(info.get("xref") or 0)
            image = ImageResult(
                page_number=page_number,
                image_index=index,
                xref=xref,
                width_px=w,
                height_px=h,
                colorspace=_colorspace_name(info),
                bits_per_component=int(info["bpc"]) if info.get("bpc") else None,
                original_format=None,
                stored_format=None,
                data=None,
                sha256=None,
                bbox=bbox,
                page_width=width,
                page_height=height,
                page_rotation=rotation,
                is_full_page=bool(bbox and page_area > 0 and _area(bbox) / page_area >= config.full_page_fraction),
                status=IMAGE_FAILED,
                error_message=None,
                ocr_status=IMG_OCR_NOT_REQUESTED,
                ocr_text=None,
                ocr_mean_confidence=None,
            )
            result.images.append(image)

            if xref <= 0:
                image.error_message = "Inline image: it is not a separate object in the PDF and cannot be extracted."
                continue
            if w * h > config.max_image_pixels:
                image.error_message = (
                    f"Image is {w}x{h} pixels, above the {config.max_image_pixels:,}-pixel limit (MAX_IMAGE_PIXELS)."
                )
                continue
            try:
                data, stored, original, _ = _extract_bytes(doc, xref)
            except Exception as exc:
                logger.warning("Image xref %s on page %d could not be extracted (%s)", xref, page_number, type(exc).__name__)
                image.error_message = f"Image could not be extracted ({type(exc).__name__})."
                continue
            if len(data) > config.max_image_bytes:
                image.error_message = (
                    f"Image is {len(data):,} bytes, above the {config.max_image_bytes:,}-byte limit (MAX_IMAGE_BYTES)."
                )
                continue

            image.data, image.stored_format, image.original_format = data, stored, original
            image.sha256 = hashlib.sha256(data).hexdigest()
            image.status = IMAGE_EXTRACTED
            if image_ocr:
                _ocr_image(image, config, ocr, result)


def _ocr_image(image: ImageResult, config: ProcessingConfig, ocr, result: PageMultimodalResult) -> None:
    if image.is_full_page:
        # The text pipeline (Phase 3) already reads full-page scans; OCR-ing the same pixels again would
        # only duplicate text.
        image.ocr_status = IMG_OCR_SKIPPED_PAGE_SCAN
        return
    try:
        png = _prepare_png_for_ocr(image.data or b"", config.max_ocr_image_side_px)
        recognised = ocr.recognize_png(png)
    except OcrUnavailableError as exc:
        image.ocr_status = IMG_OCR_UNAVAILABLE
        image.error_message = exc.message
        result.errors.append(f"Image OCR was requested but is unavailable: {exc.message}")
        return
    except OcrFailedError as exc:
        image.ocr_status = IMG_OCR_FAILED
        image.error_message = exc.message
        result.errors.append(f"Image OCR failed on one image: {exc.message}")
        return
    except Exception as exc:
        image.ocr_status = IMG_OCR_FAILED
        image.error_message = f"Image OCR failed ({type(exc).__name__})."
        result.errors.append(image.error_message)
        return

    image.ocr_mean_confidence = recognised.mean_confidence
    if count_text_chars(recognised.text) >= config.image_ocr_min_chars:
        image.ocr_status = IMG_OCR_COMPLETED
        image.ocr_text = recognised.text
    else:
        image.ocr_status = IMG_OCR_NO_TEXT
