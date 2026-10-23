"""
PDF extraction module for the CT-200 manual.

Extracts page-level text, block-level formatting information, and
table structure from a PDF.

Known limitations (read before trusting the output):

1. Heading classification is heuristic (numbered-section pattern,
   bold, font size relative to this document's own body-text
   baseline, and block brevity). Tuned against the CT-200 manual
   (v1 and v2) specifically, not validated against arbitrary PDFs.

2. Reading order follows PyMuPDF's default top-to-bottom,
   left-to-right block ordering. This does NOT always match logical
   section order. Confirmed case: in both CT-200 manual versions,
   Section 3.4 "Auto Shutoff" is physically positioned before
   Section 3.3 "Result Display and Classification" on the page.
   This module records true physical order (`block_index`) without
   correcting it -- the document tree layer decides what to do with
   that fact.

3. Table detection uses PyMuPDF's find_tables(), which on this
   document also reports "phantom" tables -- individual cells of a
   real table misdetected as tiny nested tables. This was confirmed
   by manual inspection (every phantom table's bounding box is fully
   contained inside the real table's bounding box, on every table
   page in both manual versions). Phantom tables are filtered out by
   bounding-box containment. This filter has only been validated
   against the CT-200 manuals' two known tables (Section 2.1 and
   Section 4.2) and is not guaranteed to generalize to arbitrarily
   formatted tables.

4. Tables that survive filtering are still quality-checked
   (extraction_status: "ok" or "uncertain") based on row/column
   counts and the proportion of empty cells. "uncertain" tables
   should not be trusted without manual review.

5. Figures and images are skipped (the CT-200 manuals appear to
   contain none), but this is not actively verified -- a page with
   meaningful images would silently lose that content today.


6. List detection only recognizes numbered lists that start at "1." and
   increase sequentially by 1 (e.g. "1. ... 2. ... 3. ..."), with
   non-numbered lines merged into the previous item as a wrapped
   continuation. This was confirmed against the CT-200 manual's one known
   list (Section 3.3, items 1-5, identical in both versions). Bulleted
   lists, lettered lists, and numbered lists not starting at 1 are not
   detected and will fall through as plain body text.
"""

import sys
from pathlib import Path
from collections import Counter
import re

import fitz

from document_tree import extract_section_number


MAX_HEADING_LINES = 2
MAX_HEADING_CHARS = 100
FONT_SIZE_MARGIN = 0.5

# A text block is considered "part of a table" if at least this
# fraction of its area overlaps a detected table's bounding box.
TABLE_OVERLAP_THRESHOLD = 0.8
# A line like "1. Something" starts a new list item. Lines that don't
# match are treated as a wrapped continuation of the previous item.
LIST_ITEM_PATTERN = re.compile(r"^(\d+)\.\s+(.*)$")
MIN_LIST_ITEMS = 2
# Minimum shape and maximum empty-cell ratio for a table to be
# considered reliably extracted.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
MAX_EMPTY_CELL_RATIO = 0.2


# ---------------------------------------------------------------------------
# Text block extraction
# ---------------------------------------------------------------------------

def _extract_text_blocks(page, page_number: int) -> list[dict]:
    """Extract raw text blocks for one page, with formatting info."""
    raw_blocks = page.get_text("dict", sort=True)["blocks"]
    text_blocks = []

    block_index = 0
    for raw_block in raw_blocks:
        if raw_block.get("type") != 0:
            continue  # non-text block (image/drawing) -- see limitation #5

        block_lines = []
        font_sizes = []
        is_bold = False

        for line in raw_block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span.get("text", "")
                font_sizes.append(span.get("size", 0))
                if "bold" in span.get("font", "").lower():
                    is_bold = True
            block_lines.append(line_text)

        block_text = "\n".join(block_lines).strip()
        if not block_text:
            continue

        text_blocks.append(
            {
                "page_number": page_number,
                "block_index": block_index,
                "text": block_text,
                "line_count": len(block_lines),
                "char_count": len(block_text),
                "font_size": max(font_sizes, default=0.0),
                "is_bold": is_bold,
                "bbox": tuple(raw_block.get("bbox", ())),
            }
        )
        block_index += 1

    return text_blocks


def _compute_body_font_size(all_blocks: list[dict]) -> float:
    """Estimate the document's normal body-text font size by vote-counting
    characters at each font size, rather than assuming a fixed number."""
    size_votes = Counter()
    for block in all_blocks:
        size_votes[round(block["font_size"], 1)] += block["char_count"]
    if not size_votes:
        return 0.0
    return size_votes.most_common(1)[0][0]


def classify_block(
    block: dict,
    body_font_size: float,
    is_first_page: bool,
    title_already_found: bool,
) -> dict:
    """Classify a text block as 'title', 'heading', or 'body'.
    See module docstring for why no single signal is trusted alone."""
    text = block["text"]
    section_number = extract_section_number(text)
    is_bold = block["is_bold"]
    is_larger_font = block["font_size"] > body_font_size + FONT_SIZE_MARGIN
    is_short = (
        block["line_count"] <= MAX_HEADING_LINES
        and block["char_count"] <= MAX_HEADING_CHARS
    )

    signals = []
    if section_number:
        signals.append("section_number")
    if is_bold:
        signals.append("bold")
    if is_larger_font:
        signals.append("larger_font")
    if is_short:
        signals.append("short")
    block["heading_signals"] = signals
    block["list_items"] = None  # populated later, for body blocks that are lists

    if (
        is_first_page
        and not title_already_found
        and section_number is None
        and is_bold
        and is_larger_font
    ):
        block["node_type"] = "title"
        block["section_number"] = None
        return block

    is_heading = is_short and (
        (section_number is not None and (is_bold or is_larger_font))
        or (is_bold and is_larger_font)
    )

    block["node_type"] = "heading" if is_heading else "body"
    block["section_number"] = section_number if is_heading else None
    return block
# ---------------------------------------------------------------------------
# List extraction
# ---------------------------------------------------------------------------

def _parse_list_items(text: str) -> list[dict] | None:
    """
    Detect whether a body block's text is actually a numbered list, and if
    so, parse it into items.

    Rule (confirmed against the CT-200 manual's one known list, Section 3.3,
    items 1-5, identical in both versions): a block is a list only if its
    FIRST line starts with "1. ", and subsequent numbered lines increase by
    exactly 1 each time. Any line that doesn't start with "N. " is treated
    as a wrapped continuation of the previous item's text (confirmed
    necessary -- item 5 in Section 3.3 wraps onto a second line with no
    number prefix).

    Returns None if the text doesn't qualify as a list (e.g. fewer than
    MIN_LIST_ITEMS items, doesn't start at 1, or numbers aren't sequential).

    Known limitation: only handles sequential numeric lists starting at 1.
    Bulleted lists, lettered lists, or numbered lists that don't start at 1
    are NOT detected and will be classified as plain body text instead.
    """
    lines = text.split("\n")
    items = []

    for line in lines:
        match = LIST_ITEM_PATTERN.match(line)
        if match:
            items.append({"number": int(match.group(1)), "text": match.group(2)})
        else:
            if not items:
                return None  # text before the first numbered item -> not a list
            items[-1]["text"] += " " + line.strip()

    if len(items) < MIN_LIST_ITEMS:
        return None

    expected_numbers = list(range(1, len(items) + 1))
    actual_numbers = [item["number"] for item in items]
    if actual_numbers != expected_numbers:
        return None

    return items

# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _bbox_area(bbox) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _bbox_contains(outer, inner, tolerance: float = 1.0) -> bool:
    """True if `inner` bbox sits fully inside `outer` bbox (with a small
    tolerance for floating-point/rendering slack)."""
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return (
        ix0 >= ox0 - tolerance
        and iy0 >= oy0 - tolerance
        and ix1 <= ox1 + tolerance
        and iy1 <= oy1 + tolerance
    )


def _overlap_ratio(block_bbox, table_bbox) -> float:
    """Fraction of block_bbox's area that overlaps table_bbox."""
    if not block_bbox or len(block_bbox) != 4:
        return 0.0
    bx0, by0, bx1, by1 = block_bbox
    tx0, ty0, tx1, ty1 = table_bbox
    ix0, iy0 = max(bx0, tx0), max(by0, ty0)
    ix1, iy1 = min(bx1, tx1), min(by1, ty1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter_area = (ix1 - ix0) * (iy1 - iy0)
    block_area = max(1e-6, (bx1 - bx0) * (by1 - by0))
    return inter_area / block_area


def _filter_phantom_tables(found_tables) -> list:
    """
    PyMuPDF's find_tables() additionally detects individual cells of a
    real table as small nested "tables". Confirmed by manual inspection:
    on every table page tested in both CT-200 manuals, every phantom
    table's bbox is fully contained inside the real table's (larger)
    bbox. We discard any table strictly contained inside a larger one.
    """
    kept = []
    for i, table in enumerate(found_tables):
        area = _bbox_area(table.bbox)
        is_phantom = False
        for j, other in enumerate(found_tables):
            if i == j:
                continue
            if _bbox_area(other.bbox) > area and _bbox_contains(other.bbox, table.bbox):
                is_phantom = True
                break
        if not is_phantom:
            kept.append(table)
    return kept


def _assess_table_quality(rows: list[list]) -> str:
    """Return 'ok' if the table looks like a clean grid, else 'uncertain'."""
    if len(rows) < MIN_TABLE_ROWS:
        return "uncertain"

    col_count = max((len(r) for r in rows), default=0)
    if col_count < MIN_TABLE_COLS:
        return "uncertain"

    total_cells = sum(len(r) for r in rows)
    if total_cells == 0:
        return "uncertain"

    empty_cells = sum(
        1
        for row in rows
        for cell in row
        if cell is None or (isinstance(cell, str) and cell.strip() == "")
    )
    if empty_cells / total_cells > MAX_EMPTY_CELL_RATIO:
        return "uncertain"

    return "ok"


def extract_tables(page, page_number: int) -> list[dict]:
    """Detect, filter, and quality-check tables on a page."""
    try:
        found = page.find_tables().tables
    except Exception as exc:
        return [
            {
                "page_number": page_number,
                "bbox": None,
                "row_count": 0,
                "col_count": 0,
                "rows": [],
                "extraction_status": "failed",
                "note": f"find_tables() raised an exception: {exc}",
            }
        ]

    real_tables = _filter_phantom_tables(found)

    results = []
    for table in real_tables:
        rows = table.extract()
        status = _assess_table_quality(rows)
        results.append(
            {
                "page_number": page_number,
                "bbox": tuple(table.bbox),
                "row_count": table.row_count,
                "col_count": table.col_count,
                "rows": rows,
                "extraction_status": status,
            }
        )
    return results


def _attach_nearest_heading(tables: list[dict], heading_blocks: list[dict]) -> None:
    """
    For each table, find the heading block that appears directly above
    it on the same page (largest y0 among headings whose y0 is less
    than the table's y0). Mutates each table dict in place.

    Limitation: if a table is the first thing on a page with no
    preceding heading on that same page, nearest_heading is set to
    None. We do not currently look back to the previous page's last
    heading -- this has not occurred in either CT-200 manual, but is
    an acknowledged gap, not a silent assumption.
    """
    for table in tables:
        if not table.get("bbox"):
            table["nearest_heading_section"] = None
            table["nearest_heading_text"] = None
            continue

        table_top = table["bbox"][1]
        same_page_headings = [
            h for h in heading_blocks if h["page_number"] == table["page_number"]
        ]
        candidates = [h for h in same_page_headings if h["bbox"][1] < table_top]

        if not candidates:
            table["nearest_heading_section"] = None
            table["nearest_heading_text"] = None
            continue

        nearest = max(candidates, key=lambda h: h["bbox"][1])
        table["nearest_heading_section"] = nearest.get("section_number")
        table["nearest_heading_text"] = nearest["text"]


def _remove_table_covered_blocks(
    text_blocks: list[dict], tables: list[dict]
) -> tuple[list[dict], int]:
    """
    Remove text blocks that are substantially inside a detected table's
    bbox, to avoid the same content appearing both as flattened text
    and as structured table rows. Returns (filtered_blocks, removed_count).
    """
    valid_table_bboxes = [t["bbox"] for t in tables if t.get("bbox")]
    if not valid_table_bboxes:
        return text_blocks, 0

    kept = []
    removed = 0
    for block in text_blocks:
        overlaps_table = any(
            _overlap_ratio(block["bbox"], tbbox) >= TABLE_OVERLAP_THRESHOLD
            for tbbox in valid_table_bboxes
        )
        if overlaps_table:
            removed += 1
        else:
            kept.append(block)

    return kept, removed


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: str | Path) -> dict:
    """Extract structured page/block/table data from a PDF file."""
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("The input file must be a PDF.")

    with fitz.open(pdf_path) as document:
        metadata = {
            key: value for key, value in (document.metadata or {}).items() if value
        }

        pages_text = []
        pages_raw_blocks = []
        pages_raw_tables = []
        for page_number, page in enumerate(document, start=1):
            pages_text.append(page.get_text("text", sort=True).strip())
            pages_raw_blocks.append(_extract_text_blocks(page, page_number))
            pages_raw_tables.append(extract_tables(page, page_number))

    all_blocks = [b for page_blocks in pages_raw_blocks for b in page_blocks]
    body_font_size = _compute_body_font_size(all_blocks)

    title_found = False
    pages = []
    for page_number, (page_text, blocks, tables) in enumerate(
        zip(pages_text, pages_raw_blocks, pages_raw_tables), start=1
    ):
        classified_blocks = []
        for block in blocks:
            classified = classify_block(
                block,
                body_font_size=body_font_size,
                is_first_page=(page_number == 1),
                title_already_found=title_found,
            )
            if classified["node_type"] == "title":
                title_found = True
            elif classified["node_type"] == "body":
                list_items = _parse_list_items(classified["text"])
                if list_items is not None:
                    classified["node_type"] = "list"
                    classified["list_items"] = list_items
            classified_blocks.append(classified)

        filtered_blocks, removed_count = _remove_table_covered_blocks(
            classified_blocks, tables
        )

        heading_blocks = [
            b for b in filtered_blocks if b["node_type"] in ("heading", "title")
        ]
        _attach_nearest_heading(tables, heading_blocks)

        pages.append(
            {
                "page_number": page_number,
                "text": page_text,
                "character_count": len(page_text),
                "is_empty": len(page_text) == 0,
                "text_blocks": filtered_blocks,
                "blocks_removed_as_table_content": removed_count,
                "tables": tables,
            }
        )

    return {
        "file_name": pdf_path.name,
        "page_count": len(pages),
        "metadata": metadata,
        "body_font_size": body_font_size,
        "pages": pages,
    }


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = project_root / "data" / "ct200_manual.pdf"

    result = extract_pdf(pdf_path)

    print(f"File: {result['file_name']}")
    print(f"Pages extracted: {result['page_count']}")
    print(f"Detected body font size: {result['body_font_size']}")
    print(f"Metadata: {result['metadata']}")

    print("\nPer-page stats:")
    for page in result["pages"]:
        print(
            f"Page {page['page_number']}: "
            f"{page['character_count']} chars, "
            f"{len(page['text_blocks'])} text blocks, "
            f"{len(page['tables'])} table(s), "
            f"{page['blocks_removed_as_table_content']} block(s) removed as table content, "
            f"empty={page['is_empty']}"
        )

    print("\nTitle / heading detection (in physical reading order):")
    for page in result["pages"]:
        for block in page["text_blocks"]:
            if block["node_type"] in ("title", "heading"):
                print(
                    f"Page {page['page_number']} block#{block['block_index']} "
                    f"[{block['node_type']}] section={block['section_number']} "
                    f"signals={block['heading_signals']}: {block['text']!r}"
                )

    print("\nTable extraction results:")
    for page in result["pages"]:
        for table in page["tables"]:
            print(
                f"\nPage {table['page_number']} "
                f"[{table['extraction_status']}] "
                f"{table['row_count']}x{table['col_count']} "
                f"under heading {table['nearest_heading_section']} "
                f"({table['nearest_heading_text']!r})"
            )
            for row in table["rows"]:
                print(f"   {row}")

    print("\nList detection results:")
    for page in result["pages"]:
        for block in page["text_blocks"]:
            if block["node_type"] == "list":
                print(
                    f"\nPage {page['page_number']} block#{block['block_index']} "
                    f"list with {len(block['list_items'])} item(s):"
                )
                for item in block["list_items"]:
                    print(f"   {item['number']}. {item['text']}")