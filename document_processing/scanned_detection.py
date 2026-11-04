"""Heuristics for pages that probably need OCR.

Rule (a heuristic, not a trained model, and not yet evaluated):
  * a page is *sparse* when its extracted text has fewer than `min_text_chars` non-whitespace characters;
  * a page is *likely scanned* when it is sparse AND contains at least one embedded image
    (typical of a scanned page: one full-page image and no text layer).
A sparse page without images is not called "likely scanned", but OCR is still attempted on it because
text may be drawn as vector outlines. Pages that are genuinely blank simply yield no OCR text.
"""

from document_processing.text_extraction import count_text_chars


def is_text_sparse(text: str, min_chars: int) -> bool:
    return count_text_chars(text) < min_chars


def page_has_images(page) -> bool:
    try:
        return len(page.get_images(full=False)) > 0
    except Exception:
        return False


def is_likely_scanned(text_is_sparse: bool, has_images: bool) -> bool:
    return text_is_sparse and has_images
