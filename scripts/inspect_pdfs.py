"""
Phase 1: Inspect the two CT-200 PDF manuals.

Run from the project root:
    python scripts/inspect_pdfs.py

This script reads the original PDFs without modifying them. It does not use OCR,
an LLM, a database, or FastAPI.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF 1.x
except ImportError:
    try:
        import pymupdf as fitz  # Compatible alternative for versions exposing pymupdf
    except ImportError:
        print(
            "ERROR: PyMuPDF is not installed in this Python environment.\n"
            "Install it with: python -m pip install PyMuPDF",
            file=sys.stderr,
        )
        raise SystemExit(1)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

PDF_FILES = (
    "ct200_manual.pdf",
    "ct200_manual_v2.pdf",
)

# A heuristic only: a page with fewer than this many non-whitespace characters
# may be blank, image-based, or have an extraction problem. It needs human review.
LOW_TEXT_THRESHOLD = 50
PREVIEW_LENGTH = 240


def extract_pdf(pdf_path: Path) -> dict:
    """Extract page text and report extraction issues for one PDF."""
    result = {
        "filename": pdf_path.name,
        "path": pdf_path,
        "page_count": 0,
        "pages": [],
        "status": "FAILED",
        "error": None,
        "manual_inspection_pages": [],
    }

    try:
        with fitz.open(pdf_path) as document:
            result["page_count"] = len(document)

            for page_index, page in enumerate(document):
                page_number = page_index + 1
                text = page.get_text("text") or ""
                non_whitespace_count = len("".join(text.split()))

                flags = []
                if non_whitespace_count == 0:
                    flags.append("EMPTY TEXT")
                elif non_whitespace_count < LOW_TEXT_THRESHOLD:
                    flags.append(
                        f"LOW TEXT (< {LOW_TEXT_THRESHOLD} non-whitespace characters)"
                    )

                if flags:
                    result["manual_inspection_pages"].append(page_number)

                result["pages"].append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "character_count": len(text),
                        "non_whitespace_count": non_whitespace_count,
                        "flags": flags,
                    }
                )

        result["status"] = "SUCCESS"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def save_extracted_text(result: dict) -> Path:
    """Save all page text with explicit page boundaries."""
    output_path = REPORTS_DIR / f"{Path(result['filename']).stem}_extracted_text.txt"

    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(f"Extracted text for: {result['filename']}\n")
        output.write(f"Page count: {result['page_count']}\n")
        output.write("=" * 78 + "\n")

        for page in result["pages"]:
            output.write(
                f"\n\n{'=' * 25} PAGE {page['page_number']} {'=' * 25}\n\n"
            )
            output.write(page["text"])
            if page["text"] and not page["text"].endswith("\n"):
                output.write("\n")

    return output_path


def write_summary(results: list[dict]) -> Path:
    """Write a human-readable summary of both PDF inspections."""
    summary_path = REPORTS_DIR / "phase1_inspection_summary.txt"

    with summary_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write("CT-200 PHASE 1 PDF INSPECTION SUMMARY\n")
        output.write("=" * 78 + "\n")
        output.write(f"Low-text threshold: fewer than {LOW_TEXT_THRESHOLD} ")
        output.write("non-whitespace characters per page (heuristic)\n\n")

        for result in results:
            output.write(f"File: {result['filename']}\n")
            output.write(f"Extraction status: {result['status']}\n")
            output.write(f"Page count: {result['page_count']}\n")

            if result["error"]:
                output.write(f"Error: {result['error']}\n")

            if result["status"] == "SUCCESS":
                output.write(f"Pages extracted: {len(result['pages'])}\n")
                if result["manual_inspection_pages"]:
                    pages = ", ".join(
                        str(page) for page in result["manual_inspection_pages"]
                    )
                    output.write(f"Pages requiring manual inspection: {pages}\n")
                else:
                    output.write("Pages requiring manual inspection: none flagged\n")

                for page in result["pages"]:
                    flags = "; ".join(page["flags"]) if page["flags"] else "OK"
                    output.write(
                        f"  Page {page['page_number']}: "
                        f"{page['character_count']} characters; "
                        f"{page['non_whitespace_count']} non-whitespace; "
                        f"{flags}\n"
                    )
            output.write("\n" + "-" * 78 + "\n\n")

        output.write("Important notes:\n")
        output.write(
            "- Low-text flags are a heuristic and do not prove that a page is wrong.\n"
        )
        output.write(
            "- Text extraction does not reliably reconstruct tables or visual layout.\n"
        )
        output.write(
            "- Review flagged pages and compare extracted text with the original PDFs.\n"
        )

    return summary_path


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    missing_files = [
        DATA_DIR / filename
        for filename in PDF_FILES
        if not (DATA_DIR / filename).is_file()
    ]
    if missing_files:
        print("ERROR: The following required PDF file(s) are missing:", file=sys.stderr)
        for path in missing_files:
            print(f"  - {path}", file=sys.stderr)
        print(
            "\nPlace both original manuals in the project's data/ directory.",
            file=sys.stderr,
        )
        return 1

    results = []
    for filename in PDF_FILES:
        pdf_path = DATA_DIR / filename
        print("\n" + "=" * 78)
        print(f"Inspecting: {filename}")

        result = extract_pdf(pdf_path)
        results.append(result)

        if result["status"] != "SUCCESS":
            print(f"ERROR extracting {filename}: {result['error']}")
            continue

        print(f"Actual page count: {result['page_count']}")
        for page in result["pages"]:
            preview = " ".join(page["text"].split())[:PREVIEW_LENGTH]
            if not preview:
                preview = "[NO EXTRACTABLE TEXT]"
            flags = f"  ** {'; '.join(page['flags'])} **" if page["flags"] else ""
            print(
                f"  Page {page['page_number']}: "
                f"{page['character_count']} characters "
                f"({page['non_whitespace_count']} non-whitespace){flags}"
            )
            print(f"    Preview: {preview}")

        try:
            output_path = save_extracted_text(result)
            print(f"Saved extracted text: {output_path}")
        except OSError as exc:
            result["status"] = "FAILED"
            result["error"] = f"Could not save extracted text: {exc}"
            print(f"ERROR saving extracted text: {exc}", file=sys.stderr)

    try:
        summary_path = write_summary(results)
        print(f"\nSummary report saved: {summary_path}")
    except OSError as exc:
        print(f"ERROR saving summary report: {exc}", file=sys.stderr)
        return 1

    failures = [result for result in results if result["status"] != "SUCCESS"]
    print("\nPhase 1 inspection finished.")
    if failures:
        print(f"WARNING: {len(failures)} PDF(s) failed inspection. See the summary report.")
        return 1

    print("Both PDFs were processed. Review the reports and visually inspect any flagged pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
