"""Find corpus pages whose PDF text layer already contains clock times.

Those pages give *independent* truth for in/out times: the text layer was
produced by whatever system printed the sheet, not by the OCR under test.
Same trick as tools/isgec_truth.py, applied corpus-wide.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import pypdfium2 as pdfium

BASE = Path(__file__).parent.parent
ROOTS = {"Delhi": BASE / "Timesheet - Delhi 2026-2027",
         "HO": BASE / "Timesheet - HO 2026-2027",
         "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027"}
TIME = re.compile(r'(?<![\d:])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:])')
OUT = BASE / "data" / "timelayer_pages.jsonl"

def main() -> None:
    n_pdf = n_pg = n_hit = 0
    with OUT.open("w") as fh:
        for ds, root in ROOTS.items():
            if not root.exists():
                continue
            for pdf_path in sorted(root.rglob("*.pdf")):
                n_pdf += 1
                try:
                    pdf = pdfium.PdfDocument(str(pdf_path))
                except Exception:
                    continue
                try:
                    for i in range(len(pdf)):
                        n_pg += 1
                        try:
                            txt = pdf[i].get_textpage().get_text_range()
                        except Exception:
                            continue
                        hits = TIME.findall(txt)
                        if len(hits) >= 8:
                            n_hit += 1
                            fh.write(json.dumps({
                                "dataset": ds,
                                "src": str(pdf_path.relative_to(BASE)),
                                "page": i + 1,
                                "n_times": len(hits),
                                "text": txt,
                            }) + "\n")
                finally:
                    pdf.close()
                if n_pdf % 200 == 0:
                    print(f"  {n_pdf} pdfs, {n_pg} pages, {n_hit} with a time layer", flush=True)
    print(f"DONE {n_pdf} pdfs / {n_pg} pages / {n_hit} pages carry >=8 clock times -> {OUT}")

if __name__ == "__main__":
    main()
