# CT-200 QA Assistant — Phase 1

This phase inspects the two provided CT-200 PDF manuals and saves extracted text
and a page-by-page summary. It does not modify the source PDFs and does not use
OCR, an LLM, a database, or FastAPI.

## Requirements

Python 3.12 and PyMuPDF. In the active project virtual environment:

```powershell
python -m pip install PyMuPDF==1.26.7
```

## Input files

Place the original manuals here:

```text
data/
├── ct200_manual.pdf
└── ct200_manual_v2.pdf
```

## Run from the project root

```powershell
python scripts/inspect_pdfs.py
```

## Output files

- `reports/ct200_manual_extracted_text.txt`
- `reports/ct200_manual_v2_extracted_text.txt`
- `reports/phase1_inspection_summary.txt`

Pages with fewer than 50 non-whitespace extracted characters are flagged for
manual inspection. This is only a heuristic. A page may contain a table, image,
or layout that needs visual comparison even when it has plenty of extracted text.

## Important

Keep the original PDFs unchanged. Inspect the extracted text and compare it with
the PDF pages, especially tables, page breaks, numbered headings, and lists.
