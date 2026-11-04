"""Helpers for working on a page in unrotated space."""

from contextlib import contextmanager
from typing import Iterator

from document_processing.geometry import normalise_rotation


@contextmanager
def unrotated(page) -> Iterator[tuple[float, float, int]]:
    """Temporarily set the page's rotation to 0 (in memory only; the file is never modified) and yield
    (width, height, original_rotation) of the unrotated page. Table detection and image placement
    coordinates are only consistent in this space."""
    rotation = normalise_rotation(page.rotation)
    if rotation:
        page.set_rotation(0)
    try:
        yield float(page.rect.width), float(page.rect.height), rotation
    finally:
        if rotation:
            page.set_rotation(rotation)
