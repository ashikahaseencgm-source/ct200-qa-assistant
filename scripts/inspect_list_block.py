"""
Temporary diagnostic script.

Prints every text block on page 3 (where Section 3.3's numbered list
lives in both CT-200 manual versions), showing exactly how PyMuPDF
splits it into blocks/lines. This is NOT part of the parsing pipeline
-- it exists only to see real block structure before writing any
list-detection logic.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pdf_extractor import extract_pdf


def inspect(pdf_path: Path):
    print(f"\n{'=' * 60}")
    print(f"File: {pdf_path.name}")
    print(f"{'=' * 60}")

    result = extract_pdf(pdf_path)
    page3 = next(p for p in result["pages"] if p["page_number"] == 3)

    for block in page3["text_blocks"]:
        print(f"\nblock#{block['block_index']} [{block['node_type']}] "
              f"lines={block['line_count']} chars={block['char_count']}")
        print(f"  text: {block['text']!r}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"

    inspect(data_dir / "ct200_manual.pdf")
    inspect(data_dir / "ct200_manual_v2.pdf")