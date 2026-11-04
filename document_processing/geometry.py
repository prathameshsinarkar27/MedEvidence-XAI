"""Page geometry helpers (pure Python).

Stored boxes use "unrotated page space": PDF points, origin top-left, with the page's /Rotate entry ignored
(this is the space PyMuPDF reports for tables and image placements). A viewer shows the page rotated, so
`display_region` converts a box into fractions of the *displayed* page, which is what a UI overlay needs.
"""

from document_processing.models import BBox


def normalise_rotation(rotation: int) -> int:
    return rotation % 360 if rotation % 90 == 0 else 0


def display_size(page_width: float, page_height: float, rotation: int) -> tuple[float, float]:
    """Size of the page as displayed (width and height swap for 90/270)."""
    return (page_height, page_width) if normalise_rotation(rotation) in (90, 270) else (page_width, page_height)


def display_box(bbox: BBox, page_width: float, page_height: float, rotation: int) -> BBox:
    """The box in displayed-page points (clockwise rotation, as PDF viewers apply /Rotate)."""
    x0, y0, x1, y1 = bbox
    rot = normalise_rotation(rotation)
    w, h = page_width, page_height
    if rot == 0:
        return (x0, y0, x1, y1)
    if rot == 90:  # (x, y) -> (h - y, x)
        return (h - y1, x0, h - y0, x1)
    if rot == 180:  # (x, y) -> (w - x, h - y)
        return (w - x1, h - y1, w - x0, h - y0)
    return (y0, w - x1, y1, w - x0)  # 270: (x, y) -> (y, w - x)


def display_region(bbox: BBox, page_width: float, page_height: float, rotation: int) -> tuple[float, float, float, float]:
    """(x, y, width, height) as fractions 0-1 of the displayed page, clamped to the page."""
    dw, dh = display_size(page_width, page_height, rotation)
    if dw <= 0 or dh <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    x0, y0, x1, y1 = display_box(bbox, page_width, page_height, rotation)

    def clamp(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    fx0, fy0, fx1, fy1 = clamp(x0 / dw), clamp(y0 / dh), clamp(x1 / dw), clamp(y1 / dh)
    return (round(fx0, 5), round(fy0, 5), round(fx1 - fx0, 5), round(fy1 - fy0, 5))
