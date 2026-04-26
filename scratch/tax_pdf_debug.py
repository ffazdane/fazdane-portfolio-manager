"""
Diagnostic helper — dumps raw text + table info from a PDF.
Run in a Python shell or paste into a scratch script.

Usage:
    python scratch/tax_pdf_debug.py "path/to/file.pdf"
"""
import sys, io, pdfplumber

path = sys.argv[1] if len(sys.argv) > 1 else None
if not path:
    print("Usage: python scratch/tax_pdf_debug.py <pdf_path>"); sys.exit(1)

with pdfplumber.open(path) as pdf:
    print(f"Pages: {len(pdf.pages)}")
    for i, page in enumerate(pdf.pages, 1):
        txt = page.extract_text() or ""
        tables = page.extract_tables() or []
        print(f"\n{'='*70}")
        print(f"PAGE {i}  |  tables={len(tables)}")
        print(f"{'='*70}")
        print("[TEXT EXCERPT — first 3000 chars]")
        print(txt[:3000])
        for ti, tbl in enumerate(tables):
            print(f"\n  [TABLE {ti+1}] rows={len(tbl)}")
            for ri, row in enumerate(tbl[:8]):
                print(f"    row {ri}: {row}")
        if i >= 6:
            print("\n... (stopping at page 6 for brevity)")
            break
