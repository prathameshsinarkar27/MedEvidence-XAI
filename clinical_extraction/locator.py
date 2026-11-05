"""Find where a text mention sits on its PDF page (best effort; never guesses).

The stored page text is the output of PyMuPDF `get_text("text")`. The words PyMuPDF reports with their boxes are
aligned one-to-one with the whitespace-separated tokens of that text. If the two token sequences are not
identical (for example the page text came from pdfplumber or OCR), no box is produced for that page and the
evidence simply has no region (it still has the page number and the exact source text).
"""

import re

from document_processing.page_view import unrotated

_TOKEN = re.compile(r"\S+")


class PageLocator:
    def __init__(self, tokens: list[tuple[int, int]], boxes: list[tuple[float, float, float, float]],
                 width: float, height: float, rotation: int) -> None:
        self._tokens = tokens
        self._boxes = boxes
        self.page_width, self.page_height, self.page_rotation = width, height, rotation

    def locate(self, start: int, end: int) -> tuple[float, float, float, float] | None:
        """Union box (unrotated page space, PDF points) of the words overlapping text[start:end]."""
        hit = [b for (s, e), b in zip(self._tokens, self._boxes) if s < end and start < e]
        if not hit:
            return None
        return (min(b[0] for b in hit), min(b[1] for b in hit), max(b[2] for b in hit), max(b[3] for b in hit))


def build_page_locator(page, text: str) -> PageLocator | None:
    """A locator for `page` whose stored text is `text`, or None when the words cannot be aligned exactly."""
    try:
        with unrotated(page) as (width, height, rotation):
            words = page.get_text("words")
    except Exception:
        return None
    spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    words = [w for w in words if str(w[4]).replace("\x00", "").strip()]
    if len(words) != len(spans):
        return None
    for (s, e), w in zip(spans, words):
        if text[s:e] != str(w[4]).replace("\x00", ""):
            return None
    boxes = [(float(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in words]
    return PageLocator(spans, boxes, width, height, rotation)
