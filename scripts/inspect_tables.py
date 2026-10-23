"""
Temporary diagnostic script.

Checks what PyMuPDF's find_tables() actually detects on the pages
known to contain tables in the CT-200 manuals:
  - Page 2: Section 2.1 General Specifications (2 columns)
  - Page 4: Section 4.2 Error Codes (3 columns)

This is NOT part of the parsing pipeline. It exists only to verify,
with real output, whether find_tables() is reliable enough to build
on before integrating it into pdf_extractor.py.
"""

from pathlib import Path
import fitz


def inspect(pdf_path: Path, pages_to_check: list[int]):
    print(f"\n{'=' * 60}")
    print(f"File: {pdf_path.name}")
    print(f"{'=' * 60}")

    with fitz.open(pdf_path) as doc:
        for page_number in pages_to_check:
            page = doc[page_number - 1]  # 0-indexed
            print(f"\n--- Page {page_number} ---")

            tables = page.find_tables()
            print(f"Tables found: {len(tables.tables)}")

            for i, table in enumerate(tables.tables):
                print(f"\n  Table #{i}")
                print(f"  Bounding box: {table.bbox}")
                print(f"  Row count: {table.row_count}")
                print(f"  Column count: {table.col_count}")

                extracted = table.extract()
                print("  Extracted content:")
                for row in extracted:
                    print(f"    {row}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"

    # Page 2 has the 2.1 General Specifications table (both versions).
    # Page 4 has the 4.2 Error Codes table (both versions).
    inspect(data_dir / "ct200_manual.pdf", pages_to_check=[2, 4])
    inspect(data_dir / "ct200_manual_v2.pdf", pages_to_check=[2, 4])