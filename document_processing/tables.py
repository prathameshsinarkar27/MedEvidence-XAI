"""Table detection and cell extraction for one page.

Algorithm (see docs/multimodal-processing.md):
  1. PyMuPDF `Page.find_tables()` proposes table regions and a row/column grid with one box per cell
     (ruled tables from drawn lines; borderless tables from aligned text).
  2. Cell TEXT is NOT taken from PyMuPDF's `Table.extract()`: it was observed to split decimals such as
     "7.8" into "7 8\\n.". Instead every text word on the page is assigned to the cell that contains the
     word's centre, and the words are joined in reading order. Numbers therefore stay exactly as in the PDF.
  3. Grids with fewer than 2 rows or 2 columns are not tables (lists, boxes) and are dropped; grids whose cells
     hold no text at all (decorative boxes, graphics) are dropped and counted.

Only pages with a real text layer can yield tables. Scanned pages have no words to assign; table
structure recognition from page images is out of scope.
"""

import logging

from document_processing.models import (
    TABLE_METHOD_PYMUPDF,
    BBox,
    PageMultimodalResult,
    ProcessingConfig,
    TableCellResult,
    TableResult,
)
from document_processing.page_view import unrotated
from document_processing.text_extraction import clean_text

logger = logging.getLogger(__name__)

MIN_ROWS = 2
MIN_COLS = 2


def _center_in(word: tuple, box: BBox) -> bool:
    cx = (word[0] + word[2]) / 2
    cy = (word[1] + word[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _cell_text(words: list[tuple], box: BBox) -> str:
    """Words whose centre lies in the cell, in PDF reading order; lines joined by newlines."""
    inside = [w for w in words if _center_in(w, box)]
    lines: dict[tuple[int, int], list[str]] = {}
    for w in inside:  # `words` is already in block/line/word order
        lines.setdefault((w[5], w[6]), []).append(w[4])
    return clean_text("\n".join(" ".join(parts) for parts in lines.values())).strip()


def extract_tables(page, page_number: int, config: ProcessingConfig, result: PageMultimodalResult, budget: int) -> None:
    """Fill `result.tables` for one page. `budget` is how many more tables may be stored for the document."""
    with unrotated(page) as (width, height, rotation):
        finder = page.find_tables()
        if not finder.tables:
            return
        words = page.get_text("words")
        index = 0
        for table in finder.tables:
            rows = table.rows
            row_count, col_count = table.row_count, table.col_count
            if row_count < MIN_ROWS or col_count < MIN_COLS:
                continue
            if row_count * col_count > config.max_cells_per_table:
                result.errors.append(
                    f"A detected table with {row_count} rows x {col_count} columns was not stored because it exceeds "
                    f"the {config.max_cells_per_table}-cell limit (MAX_CELLS_PER_TABLE)."
                )
                continue

            bbox: BBox = tuple(float(v) for v in table.bbox)  # type: ignore[assignment]
            nearby = [w for w in words if _center_in(w, bbox)]
            cells: list[TableCellResult] = []
            has_text = False
            for r in range(row_count):
                row_boxes = rows[r].cells if r < len(rows) else []
                for c in range(col_count):
                    box = row_boxes[c] if c < len(row_boxes) else None
                    if box is None:
                        cells.append(TableCellResult(r, c, None, None))
                        continue
                    cell_box: BBox = tuple(float(v) for v in box)  # type: ignore[assignment]
                    text = _cell_text(nearby, cell_box)
                    has_text = has_text or bool(text)
                    cells.append(TableCellResult(r, c, text, cell_box))
            if not has_text:
                result.tables_skipped_empty += 1
                continue
            if budget - len(result.tables) <= 0:
                result.tables_skipped_over_limit += 1
                continue
            index += 1
            result.tables.append(
                TableResult(
                    page_number=page_number,
                    table_index=index,
                    detection_method=TABLE_METHOD_PYMUPDF,
                    bbox=bbox,
                    page_width=width,
                    page_height=height,
                    page_rotation=rotation,
                    row_count=row_count,
                    col_count=col_count,
                    cells=cells,
                )
            )
